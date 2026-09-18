class SequoiaSqvPqcAT150 < Formula
  desc "Pinned Sequoia sqv RFC 9980 qualification candidate"
  homepage "https://sequoia-pgp.org"
  url "https://gitlab.com/sequoia-pgp/sequoia-sqv/-/archive/v1.5.0/sequoia-sqv-v1.5.0.tar.bz2"
  sha256 "695749c7b8dc006c0d5ade1830bf6263453eff8211d1e18402f6686327124800"
  license "LGPL-2.0-or-later"

  keg_only "qualification candidates are selected through exact keg paths"

  depends_on "pkgconf" => :build
  depends_on "rust" => :build
  depends_on "openssl@3.5"

  uses_from_macos "llvm" => :build

  patch :DATA

  def install
    ENV["OPENSSL_DIR"] = Formula["openssl@3.5"].opt_prefix
    ENV["OPENSSL_NO_VENDOR"] = "1"
    ENV["ASSET_OUT_DIR"] = buildpath

    system "cargo", "install", "--no-default-features",
           *std_cargo_args(features: "crypto-openssl")
    man1.install Dir["man-pages/*.1"]
    bash_completion.install "shell-completions/sqv.bash" => "sqv"
    zsh_completion.install "shell-completions/_sqv"
    fish_completion.install "shell-completions/sqv.fish"
  end

  test do
    output = shell_output("#{bin}/sqv --version 2>&1")
    assert_match "sqv 1.5.0", output
    assert_match "sequoia-openpgp 2.4.1", output
    assert_match "OpenSSL 3.5.8", output
  end
end
__END__
diff --git i/Cargo.lock w/Cargo.lock
index 53e2bae..9fbeaf9 100644
--- i/Cargo.lock
+++ w/Cargo.lock
@@ -590,0 +591,10 @@ dependencies = [
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
@@ -1374,0 +1385,12 @@ checksum = "b6d2cec3eae94f9f509c767b45932f1ada8350c4bdb85af2fcab4a3c14807981"
+[[package]]
+name = "link-section"
+version = "0.19.3"
+source = "registry+https://github.com/rust-lang/crates.io-index"
+checksum = "39c29a617ce3df32c08497bdc1ab6e2376e0b17948ac166a2fbe5977c5954cd9"
+
+[[package]]
+name = "linktime-proc-macro"
+version = "0.2.3"
+source = "registry+https://github.com/rust-lang/crates.io-index"
+checksum = "7e57c38c1e860fd37c604281cdfb1dd2216977fd76a50f85ba2f388ef3219616"
+
@@ -2105 +2127 @@ name = "sequoia-openpgp"
-version = "2.4.0"
+version = "2.4.1"
@@ -2107 +2129 @@ source = "registry+https://github.com/rust-lang/crates.io-index"
-checksum = "e421679c8175ef4674d913af7fdb8ad0078c8a2599db633ad0b4d02a06b2cb3c"
+checksum = "0fbc8f9818a6fad141d85993777ba298ee52c80a09bd23d45dda461a6b7c83cb"
@@ -2124,0 +2147 @@ dependencies = [
+ "ctor",
@@ -2150,0 +2174 @@ dependencies = [
+ "openssl-sys",
