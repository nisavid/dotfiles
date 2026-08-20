#define _GNU_SOURCE

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

enum {
  MAX_ABSENT_IDENTITIES = 64,
  MAX_RECORD_WRITE_ATTEMPTS = 256,
  AUDIT_WRITE_FAILURE_EXIT = 125
};

static pid_t absent_groups[MAX_ABSENT_IDENTITIES];
static size_t absent_group_count;
static pid_t absent_processes[MAX_ABSENT_IDENTITIES];
static size_t absent_process_count;

static bool group_was_absent(pid_t target) {
  size_t index;

  for (index = 0; index < absent_group_count; ++index) {
    if (absent_groups[index] == target) {
      return true;
    }
  }
  return false;
}

static void remember_absent_group(pid_t target) {
  if (group_was_absent(target) ||
      absent_group_count == MAX_ABSENT_IDENTITIES) {
    return;
  }
  absent_groups[absent_group_count++] = target;
}

void negative_pgid_kill_audit_remember_absent(pid_t target) {
  if (target < -1) {
    remember_absent_group(target);
  }
}

static bool process_was_absent(pid_t target) {
  size_t index;

  for (index = 0; index < absent_process_count; ++index) {
    if (absent_processes[index] == target) {
      return true;
    }
  }
  return false;
}

static void remember_absent_process(pid_t target) {
  if (process_was_absent(target) ||
      absent_process_count == MAX_ABSENT_IDENTITIES) {
    return;
  }
  absent_processes[absent_process_count++] = target;
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

static void record_stale_signal(const char *environment_name,
                                const char *identity_kind, pid_t target,
                                int signal_number) {
  const char *path = getenv(environment_name);
  char record[128];
  int descriptor;
  int length;

  if (path == NULL || *path == '\0') {
    return;
  }
  descriptor = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW,
                    0600);
  if (descriptor < 0) {
    return;
  }
  length = snprintf(record, sizeof(record),
                    "stale-%s-signal target=%ld signal=%d\n", identity_kind,
                    (long)target, signal_number);
  if (length > 0 && (size_t)length < sizeof(record)) {
    if (!write_complete_record(descriptor, record, (size_t)length)) {
      _exit(AUDIT_WRITE_FAILURE_EXIT);
    }
  }
  if (close(descriptor) != 0) {
    _exit(AUDIT_WRITE_FAILURE_EXIT);
  }
}

static void observe_result(pid_t target, int signal_number, int result,
                           int saved_errno) {
  if (target >= -1) {
    const char *positive_log = getenv("POSITIVE_PID_KILL_AUDIT_LOG");

    if (target <= 1 || positive_log == NULL || *positive_log == '\0') {
      return;
    }
    if (signal_number == 0 && result == -1 && saved_errno == ESRCH) {
      remember_absent_process(target);
    }
    return;
  }
  if (signal_number == 0 && result == -1 && saved_errno == ESRCH) {
    remember_absent_group(target);
    return;
  }
  if ((signal_number == SIGHUP || signal_number == SIGTERM ||
       signal_number == SIGKILL) &&
      (group_was_absent(target) || (result == -1 && saved_errno == ESRCH))) {
    record_stale_signal("NEGATIVE_PGID_KILL_AUDIT_LOG", "negative-pgid",
                        target, signal_number);
  }
}

int kill(pid_t target, int signal_number) {
  static int (*real_kill)(pid_t, int);
  int result;
  int saved_errno;

  if (real_kill == NULL) {
    real_kill = (int (*)(pid_t, int))dlsym(RTLD_NEXT, "kill");
    if (real_kill == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  if (target > 1 &&
      (signal_number == SIGTERM || signal_number == SIGKILL) &&
      process_was_absent(target)) {
    record_stale_signal("POSITIVE_PID_KILL_AUDIT_LOG", "positive-pid", target,
                        signal_number);
    errno = ESRCH;
    return -1;
  }
  result = real_kill(target, signal_number);
  saved_errno = errno;
  observe_result(target, signal_number, result, saved_errno);
  errno = saved_errno;
  return result;
}

int killpg(pid_t process_group, int signal_number) {
  static int (*real_killpg)(pid_t, int);
  pid_t target = -process_group;
  int result;
  int saved_errno;

  if (real_killpg == NULL) {
    real_killpg = (int (*)(pid_t, int))dlsym(RTLD_NEXT, "killpg");
    if (real_killpg == NULL) {
      errno = ENOSYS;
      return -1;
    }
  }
  result = real_killpg(process_group, signal_number);
  saved_errno = errno;
  observe_result(target, signal_number, result, saved_errno);
  errno = saved_errno;
  return result;
}
