#define _GNU_SOURCE

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

enum {
  STATUS_PREFIX_LENGTH = 3,
  MAX_PENDING_LENGTH = 32,
  DEADLINE_PENDING_YIELDS = 64,
  DELAYED_TAIL_MINIMUM_YIELDS = 16,
  DELAYED_TAIL_NANOSECONDS = 160000000,
  DEADLINE_SHIFT_SECONDS = 3600,
  IDENTITY_EXIT_WAIT_NANOSECONDS = 1000000,
  IDENTITY_GATE_WAIT_ATTEMPTS = 10000,
  MAX_RECORD_WRITE_ATTEMPTS = 64,
  AUDIT_WRITE_FAILURE_EXIT = 125
};

static int fragmented_descriptor = -1;
static char pending_status[MAX_PENDING_LENGTH];
static size_t pending_offset;
static size_t pending_length;
static size_t pending_yields_remaining;
static bool status_was_fragmented;
static int status_prefix_descriptor = -1;
static size_t status_prefix_length;
static bool deadline_marker_recorded;
static bool deadline_tail_recorded;
static bool delayed_tail_marker_recorded;
static bool delayed_tail_yields_marker_recorded;
static size_t delayed_tail_forced_yields;
static struct timespec delayed_tail_deadline;
static bool zpty_child_process;
static bool identity_race_consumed;
static bool post_active_loss_triggered;
static pid_t managed_zpty_pid = -1;
static pid_t fixture_owner_pid = -1;

__attribute__((constructor)) static void initialize_fixture_owner(void) {
  const char *owner_text = getenv("ZPTY_IDENTITY_LOSS_OWNER_PID");

  if (owner_text != NULL && *owner_text != '\0') {
    char *end = NULL;
    long owner = strtol(owner_text, &end, 10);

    if (end != owner_text && *end == '\0' && owner > 1) {
      fixture_owner_pid = (pid_t)owner;
      return;
    }
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  fixture_owner_pid = getpid();
  char owner_record[64];
  int length = snprintf(owner_record, sizeof(owner_record), "%ld",
                        (long)fixture_owner_pid);
  if (length <= 0 || (size_t)length >= sizeof(owner_record) ||
      setenv("ZPTY_IDENTITY_LOSS_OWNER_PID", owner_record, 1) != 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
}

static bool write_complete_record(int descriptor, const char *record,
                                  size_t length) {
  size_t attempt;
  size_t offset = 0;

  for (attempt = 0;
       offset < length && attempt < MAX_RECORD_WRITE_ATTEMPTS; ++attempt) {
    ssize_t written = write(descriptor, record + offset, length - offset);

    if (written > 0) {
      offset += (size_t)written;
      continue;
    }
    if (written < 0 && errno == EINTR) {
      continue;
    }
    return false;
  }
  return offset == length;
}

static void record_marker(const char *environment_name, const char *record) {
  const char *path = getenv(environment_name);
  int descriptor;
  size_t length;

  if (path == NULL || *path == '\0') {
    return;
  }
  descriptor = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW,
                    0600);
  if (descriptor < 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  length = strlen(record);
  if (!write_complete_record(descriptor, record, length) ||
      close(descriptor) != 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
}

static bool is_pty_master(int descriptor) {
  unsigned int pty_number;

  return ioctl(descriptor, TIOCGPTN, &pty_number) == 0;
}

static bool deadline_expiration_requested(void) {
  return getenv("ZPTY_STATUS_FRAGMENT_EXPIRE_DEADLINE") != NULL;
}

static bool delayed_tail_requested(void) {
  return getenv("ZPTY_STATUS_FRAGMENT_DELAY_TAIL") != NULL;
}

static void arm_delayed_tail(void) {
  if (syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &delayed_tail_deadline) != 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  delayed_tail_deadline.tv_nsec += DELAYED_TAIL_NANOSECONDS;
  if (delayed_tail_deadline.tv_nsec >= 1000000000) {
    ++delayed_tail_deadline.tv_sec;
    delayed_tail_deadline.tv_nsec -= 1000000000;
  }
  record_marker("ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG", "delay-armed\n");
}

static bool delayed_tail_is_pending(void) {
  struct timespec now;

  if (!delayed_tail_requested()) {
    return false;
  }
  if (syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &now) != 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  return now.tv_sec < delayed_tail_deadline.tv_sec ||
         (now.tv_sec == delayed_tail_deadline.tv_sec &&
          now.tv_nsec < delayed_tail_deadline.tv_nsec);
}

static bool delayed_tail_needs_forced_yield(void) {
  if (!delayed_tail_requested() ||
      delayed_tail_forced_yields >= DELAYED_TAIL_MINIMUM_YIELDS) {
    return false;
  }
  ++delayed_tail_forced_yields;
  if (delayed_tail_forced_yields == DELAYED_TAIL_MINIMUM_YIELDS &&
      !delayed_tail_yields_marker_recorded) {
    delayed_tail_yields_marker_recorded = true;
    record_marker("ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG",
                  "forced-yields-complete\n");
  }
  return true;
}

static bool initial_identity_loss_requested(void) {
  return getenv("ZPTY_INITIAL_IDENTITY_LOSS") != NULL;
}

static void wait_for_initial_identity_loss_gate(void) {
  const char *gate_path = getenv("ZPTY_INITIAL_IDENTITY_LOSS_GATE");
  const struct timespec interval = {0, IDENTITY_EXIT_WAIT_NANOSECONDS};
  size_t attempt;

  if (gate_path == NULL || *gate_path == '\0') {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  for (attempt = 0; attempt < IDENTITY_GATE_WAIT_ATTEMPTS; ++attempt) {
    if (access(gate_path, F_OK) == 0) {
      return;
    }
    if (errno != ENOENT) {
      _exit(AUDIT_WRITE_FAILURE_EXIT);
    }
    nanosleep(&interval, NULL);
  }
  _exit(AUDIT_WRITE_FAILURE_EXIT);
}

static void record_initial_controller(pid_t controller) {
  char record[64];
  int length = snprintf(record, sizeof(record), "controller:%ld\n",
                        (long)controller);

  if (length <= 0 || (size_t)length >= sizeof(record)) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
  record_marker("ZPTY_IDENTITY_LOSS_AUDIT_LOG", record);
}

static bool post_active_identity_loss_requested(void) {
  return getenv("ZPTY_POST_ACTIVE_IDENTITY_LOSS") != NULL;
}

static bool identity_loss_requested(void) {
  return initial_identity_loss_requested() ||
         post_active_identity_loss_requested();
}

static bool caller_is_zpty_module(void *address) {
  Dl_info information;

  return dladdr(address, &information) != 0 && information.dli_fname != NULL &&
         strstr(information.dli_fname, "/zsh/zpty.so") != NULL;
}

pid_t fork(void) {
  static pid_t (*real_fork)(void);
  bool owner_fork;
  bool zpty_fork;
  pid_t result;

  if (real_fork == NULL) {
    real_fork = (pid_t(*)(void))dlsym(RTLD_NEXT, "fork");
    if (real_fork == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  owner_fork = getpid() == fixture_owner_pid;
  zpty_fork = owner_fork && identity_loss_requested() &&
              !identity_race_consumed &&
              caller_is_zpty_module(__builtin_return_address(0));
  result = real_fork();
  if (result == 0) {
    if (zpty_fork) {
      zpty_child_process = true;
      identity_race_consumed = true;
    } else if (owner_fork) {
      fixture_owner_pid = getpid();
    } else if (zpty_child_process) {
      zpty_child_process = false;
    }
    return 0;
  }
  if (result > 0 && zpty_fork) {
    identity_race_consumed = true;
    managed_zpty_pid = result;
    if (initial_identity_loss_requested()) {
      record_initial_controller(result);
      wait_for_initial_identity_loss_gate();
      record_marker("ZPTY_IDENTITY_LOSS_AUDIT_LOG",
                    "initial-identity-loss\n");
    }
  }
  return result;
}

ssize_t write(int descriptor, const void *buffer, size_t count) {
  static ssize_t (*real_write)(int, const void *, size_t);
  ssize_t result;

  if (real_write == NULL) {
    real_write =
        (ssize_t(*)(int, const void *, size_t))dlsym(RTLD_NEXT, "write");
    if (real_write == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  result = real_write(descriptor, buffer, count);
  if (result > 0 && post_active_identity_loss_requested() &&
      !post_active_loss_triggered && managed_zpty_pid > 1 &&
      is_pty_master(descriptor)) {
    post_active_loss_triggered = true;
    syscall(SYS_kill, -managed_zpty_pid, SIGKILL);
    record_marker("ZPTY_IDENTITY_LOSS_AUDIT_LOG",
                  "post-active-identity-loss\n");
  }
  return result;
}

int close(int descriptor) {
  static int (*real_close)(int);

  if (real_close == NULL) {
    real_close = (int (*)(int))dlsym(RTLD_NEXT, "close");
    if (real_close == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  if (descriptor == fragmented_descriptor) {
    fragmented_descriptor = -1;
    pending_offset = 0;
    pending_length = 0;
    pending_yields_remaining = 0;
  }
  return real_close(descriptor);
}

static void record_expired_deadline(void) {
  if (!deadline_marker_recorded) {
    deadline_marker_recorded = true;
    record_marker("ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG",
                  "deadline-expired\n");
  }
}

static void expire_realtime_seconds(time_t *seconds) {
  if (status_was_fragmented && deadline_expiration_requested()) {
    *seconds += DEADLINE_SHIFT_SECONDS;
    record_expired_deadline();
  }
}

static ssize_t deliver_pending_status(int descriptor, void *buffer,
                                      size_t count) {
  size_t available;
  size_t delivered;

  if (descriptor != fragmented_descriptor) {
    return -2;
  }
  if (pending_yields_remaining > 0) {
    --pending_yields_remaining;
    errno = EAGAIN;
    return -1;
  }
  if (delayed_tail_needs_forced_yield() || delayed_tail_is_pending()) {
    errno = EAGAIN;
    return -1;
  }
  if (delayed_tail_requested() && !delayed_tail_marker_recorded) {
    delayed_tail_marker_recorded = true;
    record_marker("ZPTY_STATUS_FRAGMENT_DELAY_AUDIT_LOG", "delayed-tail\n");
  }
  if (deadline_expiration_requested() && !deadline_tail_recorded) {
    deadline_tail_recorded = true;
    record_marker("ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG",
                  "post-deadline-tail\n");
  }
  if (pending_offset >= pending_length) {
    fragmented_descriptor = -1;
    return -2;
  }
  available = pending_length - pending_offset;
  delivered = count < available ? count : available;
  memcpy(buffer, pending_status + pending_offset, delivered);
  pending_offset += delivered;
  if (pending_offset == pending_length) {
    fragmented_descriptor = -1;
    pending_offset = 0;
    pending_length = 0;
  }
  return (ssize_t)delivered;
}

ssize_t read(int descriptor, void *buffer, size_t count) {
  static const char status_prefix[] = "sta";
  static ssize_t (*real_read)(int, void *, size_t);
  size_t index;
  ssize_t pending_result;
  ssize_t result;

  if (real_read == NULL) {
    real_read = (ssize_t(*)(int, void *, size_t))dlsym(RTLD_NEXT, "read");
    if (real_read == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }

  pending_result = deliver_pending_status(descriptor, buffer, count);
  if (pending_result != -2) {
    return pending_result;
  }

  result = real_read(descriptor, buffer, count);
  if (result <= 0 || status_was_fragmented || !is_pty_master(descriptor)) {
    return result;
  }

  if (status_prefix_descriptor != descriptor) {
    status_prefix_descriptor = descriptor;
    status_prefix_length = 0;
  }
  for (index = 0; index < (size_t)result; ++index) {
    if (((const char *)buffer)[index] != status_prefix[status_prefix_length]) {
      status_prefix_descriptor = -1;
      status_prefix_length = 0;
      return result;
    }
    ++status_prefix_length;
    if (status_prefix_length == STATUS_PREFIX_LENGTH) {
      size_t fragment_length = index + 1;
      size_t remainder_length = (size_t)result - fragment_length;

      if (remainder_length > MAX_PENDING_LENGTH) {
        status_prefix_descriptor = -1;
        status_prefix_length = 0;
        return result;
      }
      fragmented_descriptor = descriptor;
      pending_offset = 0;
      pending_length = remainder_length;
      if (remainder_length > 0) {
        memcpy(pending_status, (const char *)buffer + fragment_length,
               remainder_length);
      }
      pending_yields_remaining =
          deadline_expiration_requested() ? DEADLINE_PENDING_YIELDS : 1;
      record_marker("ZPTY_STATUS_FRAGMENT_AUDIT_LOG", "fragmented-status\n");
      if (deadline_expiration_requested()) {
        record_marker("ZPTY_STATUS_FRAGMENT_DEADLINE_AUDIT_LOG",
                      "deadline-armed\n");
      }
      if (delayed_tail_requested()) {
        arm_delayed_tail();
      }
      status_was_fragmented = true;

      if (getenv("ZPTY_STATUS_FRAGMENT_PAUSE") != NULL) {
        pause();
        errno = EINTR;
        return -1;
      }
      return (ssize_t)fragment_length;
    }
  }
  return result;
}

int clock_gettime(clockid_t clock_identifier, struct timespec *timestamp) {
  static int (*real_clock_gettime)(clockid_t, struct timespec *);
  int result;

  if (real_clock_gettime == NULL) {
    real_clock_gettime =
        (int (*)(clockid_t, struct timespec *))dlsym(RTLD_NEXT, "clock_gettime");
    if (real_clock_gettime == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  result = real_clock_gettime(clock_identifier, timestamp);
  if (result == 0 && clock_identifier == CLOCK_REALTIME) {
    expire_realtime_seconds(&timestamp->tv_sec);
  }
  return result;
}

int gettimeofday(struct timeval *time_value, void *timezone_value) {
  static int (*real_gettimeofday)(struct timeval *, void *);
  int result;

  if (real_gettimeofday == NULL) {
    real_gettimeofday =
        (int (*)(struct timeval *, void *))dlsym(RTLD_NEXT, "gettimeofday");
    if (real_gettimeofday == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  result = real_gettimeofday(time_value, timezone_value);
  if (result == 0) {
    expire_realtime_seconds(&time_value->tv_sec);
  }
  return result;
}
