#!/usr/bin/env bash
# Provision a Buildkite hosted agent and run one scripts/ci-test-group group.
#
# Tool versions and digests match .github/workflows/platform-portability.yml.
# Linux hosted jobs start as root, so the tests run as an unprivileged user,
# as they do on GitHub-hosted runners.
set -euo pipefail

readonly CHEZMOI_VERSION=2.71.0
readonly AGE_VERSION=1.3.1
readonly UV_VERSION=0.11.32
readonly PYTHON_VERSION=3.12
# privacy-scan allows /home/runner paths, matching GitHub-hosted runners.
readonly CI_USER=runner

fetch_verified() {
  local url=$1 digest=$2 dest=$3
  curl --fail --location --silent --show-error --output "$dest" "$url"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$digest" "$dest" | sha256sum --check --quiet
  else
    printf '%s  %s\n' "$digest" "$dest" | shasum -a 256 --check --quiet
  fi
}

install_tools() {
  local tools=$1 platform=$2 python=$3
  [[ ! -f $tools/.installed ]] || return 0
  local chezmoi_digest age_digest uv_asset uv_digest
  case "$platform" in
    linux-amd64)
      chezmoi_digest=6ea2040ecc0e82d3dac604289e100b0157afefcd94ebb818e5f6e31655156d34
      age_digest=bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377
      uv_asset=uv-x86_64-unknown-linux-gnu
      uv_digest=aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967
      ;;
    darwin-arm64)
      chezmoi_digest=8b03d7be6b5d500a503c712ae6da7dd6817b6c3328223b4ae8be7a8be5a2fa3a
      age_digest=01120ea2cbf0463d4c6bd767f99f3271bbed1cdc8a9aa718a76ba1fe4f01998b
      uv_asset=uv-aarch64-apple-darwin
      uv_digest=ed336d0ba49db8ef89b2b41fffa372ce63bd032f22a56f001c265891aec32829
      ;;
    *)
      printf 'run-group: unsupported platform: %s\n' "$platform" >&2
      return 1
      ;;
  esac
  local chezmoi_platform=${platform/-/_} downloads=$tools/downloads
  mkdir -p "$tools/bin" "$downloads"
  fetch_verified \
    "https://github.com/twpayne/chezmoi/releases/download/v${CHEZMOI_VERSION}/chezmoi_${CHEZMOI_VERSION}_${chezmoi_platform}.tar.gz" \
    "$chezmoi_digest" "$downloads/chezmoi.tar.gz"
  tar -xzf "$downloads/chezmoi.tar.gz" -C "$tools/bin" chezmoi
  fetch_verified \
    "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-${platform}.tar.gz" \
    "$age_digest" "$downloads/age.tar.gz"
  tar -xzf "$downloads/age.tar.gz" -C "$downloads"
  install -m 0755 "$downloads/age/age" "$downloads/age/age-keygen" \
    "$downloads/age/age-inspect" "$tools/bin"
  fetch_verified \
    "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${uv_asset}.tar.gz" \
    "$uv_digest" "$downloads/uv.tar.gz"
  tar -xzf "$downloads/uv.tar.gz" -C "$downloads"
  install -m 0755 "$downloads/$uv_asset/uv" "$downloads/$uv_asset/uvx" "$tools/bin"
  if [[ -n $python ]]; then
    "$tools/bin/uv" venv --quiet --python "$python" "$tools/venv"
  else
    UV_PYTHON_INSTALL_DIR=$tools/python "$tools/bin/uv" venv --quiet \
      --python "$PYTHON_VERSION" --python-preference only-managed "$tools/venv"
  fi
  rm -rf "$downloads"
  touch "$tools/.installed"
}

record_timing() {
  local key=$1 value=$2
  command -v buildkite-agent >/dev/null 2>&1 || return 0
  buildkite-agent meta-data set "$key" "$value" || true
}

main() {
  if [[ $# -ne 1 ]]; then
    printf 'usage: run-group.sh GROUP\n' >&2
    return 64
  fi
  local group=$1 script_path repo_root os platform tools status=0
  script_path="$(realpath -- "${BASH_SOURCE[0]}")"
  repo_root="${script_path%/*/*}"
  cd -- "$repo_root"

  os="$(uname -s)"
  local started_at
  started_at="$(date +%s)"
  case "$os" in
    Linux)
      [[ "$(id -u)" -eq 0 ]] || {
        printf 'run-group: Linux jobs are expected to start as root\n' >&2
        return 1
      }
      platform=linux-amd64
      tools=/opt/dotfiles-ci
      export DEBIAN_FRONTEND=noninteractive
      apt-get -qq update
      apt-get -qq install -y --no-install-recommends \
        acl bat ca-certificates curl gcc git jq libc6-dev openssh-client procps psmisc \
        python3 ripgrep systemd util-linux zsh >/dev/null
      [[ -e /usr/local/bin/bat ]] || ln -s /usr/bin/batcat /usr/local/bin/bat
      install_tools "$tools" "$platform" /usr/bin/python3
      chmod -R a+rX "$tools"
      id -u "$CI_USER" >/dev/null 2>&1 ||
        useradd --create-home --shell /bin/bash "$CI_USER"
      chown -R "$CI_USER:" "$repo_root"
      # Some tests create scratch directories beside the checkout, as the
      # GitHub-hosted runner user can.
      chown "$CI_USER:" "${repo_root%/*}"
      runuser -u "$CI_USER" -- env -i \
        HOME="/home/$CI_USER" USER="$CI_USER" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
        PATH="$tools/venv/bin:$tools/bin:/usr/local/bin:/usr/bin:/bin" \
        AGE_TOOLING_DIRECTORY="$tools/bin" \
        bash scripts/ci-test-group "$group" || status=$?
      ;;
    Darwin)
      platform=darwin-arm64
      [[ "$(uname -m)" == arm64 ]] || platform=unsupported
      tools="${TMPDIR:-/tmp}/dotfiles-ci"
      HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 \
        HOMEBREW_NO_ENV_HINTS=1 brew install --quiet bat flock jq ripgrep
      install_tools "$tools" "$platform" ""
      PYTHONDONTWRITEBYTECODE=1 PATH="$tools/venv/bin:$tools/bin:$PATH" \
        AGE_TOOLING_DIRECTORY="$tools/bin" \
        bash scripts/ci-test-group "$group" || status=$?
      ;;
    *)
      printf 'run-group: unsupported OS: %s\n' "$os" >&2
      return 1
      ;;
  esac
  record_timing "timing:$os:$group" "$started_at $(date +%s) $status"
  return "$status"
}

main "$@"
