# Shared fixtures and assertions.

cleanup_fixtures() {
  local fixture_root
  for fixture_root in ${fixtures[@]}; do
    [[ -d $fixture_root ]] || continue
    find $fixture_root -type d -exec chmod u+rwx {} +
    rm -rf -- $fixture_root
  done
}

fail() {
  print -u2 -r -- "FAIL: $*"
  return 1
}

assert_eq() {
  [[ $1 == $2 ]] || fail "expected <$1> to equal <$2>"
}

new_fixture() {
  fixture=$(mktemp -d "${TMPDIR:-/tmp}/private-skill-transaction.XXXXXX")
  fixture=${fixture:A}
  fixtures+=($fixture)
  export HOME=$fixture/home
  export XDG_STATE_HOME=$fixture/state
  mkdir -m 700 -p $HOME $XDG_STATE_HOME
  mkdir -m 700 $XDG_STATE_HOME/chezmoi
}

make_age_fixture() {
  mkdir -m 700 -p $fixture/source $fixture/plain
  age-keygen -o $fixture/identity.txt >/dev/null 2>&1
  recipient=$(age-keygen -y $fixture/identity.txt)
}

encrypt_value() {
  local value=$1 output=$2 plain=$fixture/plain/input
  print -rn -- $value >$plain
  chmod 600 $plain
  age -r $recipient -o $output $plain
  rm -f $plain
}

skill_text() {
  local name=$1 body=$2
  printf '%s\n' '---' "name: $name" 'description: test fixture' '---' '' "$body"
}

install_fake_chezmoi() {
  (($# == 1)) || fail 'fake chezmoi mode is required'
  mkdir -m 700 -p $fixture/bin
  ln -s $test_dir/fake-chezmoi $fixture/bin/fake-chezmoi
  export PRIVATE_SKILL_FAKE_MODE=$1
}
