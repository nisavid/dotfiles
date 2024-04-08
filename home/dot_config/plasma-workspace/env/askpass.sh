# shellcheck shell=sh

for _askpass in kwalletaskpass ksshaskpass lxqt-openssh-askpass x11-ssh-askpass; do
	_askpass_bin="$(which "$_askpass" 2>/dev/null)" || continue
	export SSH_ASKPASS="$_askpass_bin"
	export SSH_ASKPASS_REQUIRE=prefer
	break
done
unset _askpass _askpass_bin
