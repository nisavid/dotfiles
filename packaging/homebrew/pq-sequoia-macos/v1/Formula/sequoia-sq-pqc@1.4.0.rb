class SequoiaSqPqcAT140 < Formula
  desc "Pinned Sequoia sq RFC 9980 qualification candidate"
  homepage "https://sequoia-pgp.org"
  url "https://gitlab.com/sequoia-pgp/sequoia-sq/-/archive/v1.4.0/sequoia-sq-v1.4.0.tar.gz"
  sha256 "c856bfb0f0c94a1b8f4b72a04a6eff1e1d3d24c377cb0b1e495688e9aad8467a"
  license "LGPL-2.0-or-later"

  keg_only "qualification candidates are selected through exact keg paths"

  depends_on "capnp" => :build
  depends_on "pkgconf" => :build
  depends_on "rust" => :build
  depends_on "openssl@3.5"

  uses_from_macos "llvm" => :build
  uses_from_macos "bzip2"
  uses_from_macos "sqlite"

  patch :DATA

  def install
    ENV["OPENSSL_DIR"] = Formula["openssl@3.5"].opt_prefix
    ENV["OPENSSL_NO_VENDOR"] = "1"
    ENV["ASSET_OUT_DIR"] = buildpath

    system "cargo", "install", "--no-default-features",
           *std_cargo_args(features: "crypto-openssl")
    man1.install Dir["man-pages/*.1"]
    bash_completion.install "shell-completions/sq.bash" => "sq"
    zsh_completion.install "shell-completions/_sq"
    fish_completion.install "shell-completions/sq.fish"
  end

  test do
    output = shell_output("#{bin}/sq version 2>&1")
    assert_match "sq 1.4.0", output
    assert_match "sequoia-openpgp 2.4.1", output
    assert_match "OpenSSL 3.5.8", output
  end
end
__END__
diff --git i/Cargo.lock w/Cargo.lock
index 395a2577..eebfe925 100644
--- i/Cargo.lock
+++ w/Cargo.lock
@@ -816,0 +817,10 @@ dependencies = [
+[[package]]
+name = "ctor"
+version = "1.0.13"
+source = "registry+https://github.com/rust-lang/crates.io-index"
+checksum = "914a755b7c2d4af2bdcff7ce1739e2db9a1b81a9b07123d8015786ae03c0980d"
+dependencies = [
+ "link-section",
+ "linktime-proc-macro",
+]
+
@@ -1066 +1076 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.59.0",
@@ -1299 +1309 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.52.0",
@@ -2463,0 +2474,6 @@ checksum = "9e69cdf6b85b5c8dce514f694089a2cf8b1a702f6cd28607bcb3cf296c9778db"
+[[package]]
+name = "link-section"
+version = "0.19.3"
+source = "registry+https://github.com/rust-lang/crates.io-index"
+checksum = "39c29a617ce3df32c08497bdc1ab6e2376e0b17948ac166a2fbe5977c5954cd9"
+
@@ -2469,0 +2486,6 @@ checksum = "0717cef1bc8b636c6e1c1bbdefc09e6322da8a9321966e8928ef80d20f7f770f"
+[[package]]
+name = "linktime-proc-macro"
+version = "0.2.3"
+source = "registry+https://github.com/rust-lang/crates.io-index"
+checksum = "7e57c38c1e860fd37c604281cdfb1dd2216977fd76a50f85ba2f388ef3219616"
+
@@ -2695 +2717 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -2771 +2793 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.59.0",
@@ -2883 +2905 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3672 +3694 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.52.0",
@@ -3820 +3842 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3853 +3875 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3866 +3888 @@ dependencies = [
- "ctor",
+ "ctor 0.6.3",
@@ -3876 +3898 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3902 +3924 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3920 +3942 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3986 +4008 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -3994 +4016 @@ name = "sequoia-openpgp"
-version = "2.4.0"
+version = "2.4.1"
@@ -3996 +4018 @@ source = "registry+https://github.com/rust-lang/crates.io-index"
-checksum = "e421679c8175ef4674d913af7fdb8ad0078c8a2599db633ad0b4d02a06b2cb3c"
+checksum = "0fbc8f9818a6fad141d85993777ba298ee52c80a09bd23d45dda461a6b7c83cb"
@@ -4013,0 +4036 @@ dependencies = [
+ "ctor 1.0.13",
@@ -4039,0 +4063 @@ dependencies = [
+ "openssl-sys",
@@ -4054 +4078 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -4074 +4098 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -4142 +4166 @@ dependencies = [
- "thiserror 2.0.18",
+ "thiserror 1.0.69",
@@ -4621 +4645 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.52.0",
@@ -4650 +4674 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.59.0",
@@ -4669 +4693 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.59.0",
@@ -5321 +5345 @@ dependencies = [
- "windows-sys 0.61.2",
+ "windows-sys 0.48.0",
