class PimuxPreview < Formula
  include Language::Python::Virtualenv

  desc "Native terminal and explicit multi-server CLI source preview"
  homepage "https://github.com/2-mo/pimux"
  url "https://github.com/2-mo/pimux/releases/download/v1.0.0-beta.2/pimux-source.tar.gz"
  version "1.0.0-beta.2"
  sha256 "3fe8b8a62a29d144f14f7fbdc37b1704eb4212c1181d2f5361d160efdbe18f33"
  license "Apache-2.0"
  revision 1

  depends_on "bash"
  depends_on macos: :sequoia
  depends_on "ncurses"
  depends_on "python@3.14"
  depends_on "tmux"

  resource "blessed" do
    url "https://files.pythonhosted.org/packages/29/1f/88e64e3b4a8299fcc47dd0db35276ca21c18fadad4e8eb25afad546404c6/blessed-1.52.0-py3-none-any.whl", using: :nounzip
    sha256 "1936f421f3feb130035a4629e6477d1432e33b2674ab2b9841292c74d479eac2"
  end

  resource "jinxed" do
    url "https://files.pythonhosted.org/packages/f1/1d/0a6be99b69bb448448403a45a241aff0dca751832ae54f027ed940d2eb52/jinxed-2.1.0-py2.py3-none-any.whl", using: :nounzip
    sha256 "43b802d18b70e405d410fb66eb2837d1101e7e5ea922e666507bb43f34d11d09"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/b3/81/4da04ced5a082363ecfa159c010d200ecbd959ae410c10c0264a38cac0f5/markdown_it_py-4.2.0-py3-none-any.whl", using: :nounzip
    sha256 "9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl", using: :nounzip
    sha256 "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/71/46/17f022dd3e953bf20a04a028a21ec746d942f8d2af30fa0f124fa0e6a684/pygments-2.21.0-py3-none-any.whl", using: :nounzip
    sha256 "2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/82/3b/64d4899d73f91ba49a8c18a8ff3f0ea8f1c1d75481760df8c68ef5235bf5/rich-15.0.0-py3-none-any.whl", using: :nounzip
    sha256 "33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/6f/0c/309b1813b230d1dbbd6f2c2ab2bb21ef68992358977605d9ef289bbfedcc/wcwidth-0.9.4-py3-none-any.whl", using: :nounzip
    sha256 "901eace6d2dd25ebb917d0ce5db18e5c537e1504c905cf32f0d006c12098b05d"
  end

  def install
    libexec.install "bin", "lib", "config"
    version_check = <<~'SH'
      source "$1" || exit
      version=$("$2" -V) || exit
      pimux_tmux_version_supported "$version" || {
        printf 'tmux >= %s required; found %s\n' "$PIMUX_TMUX_MINIMUM" "$version" >&2
        exit 1
      }
    SH
    system formula_opt_bin("bash")/"bash", "-c", version_check,
           "pimux-check", libexec/"lib/tmux_compat.bash", formula_opt_bin("tmux")/"tmux"
    (libexec/".pimux-homebrew").write "pimux-preview\n"
    (libexec/"source-commit").write "133011a2533be8849061c92bdb9e2109781ade2a" + "\n"
    pkgshare.install "docs", "packaging/homebrew/README.md"

    python = formula_opt_bin("python@3.14")/"python3.14"
    virtualenv_create(libexec/".venv", python, system_site_packages: false)
    # Locked universal Python wheels avoid unpinned build backends or pip resolution.
    resources.each do |r|
      r.stage do
        wheel = Dir["*.whl"].fetch(0)
        system python, "-m", "pip", "--python=#{libexec}/.venv/bin/python", "install",
               "--no-index", "--no-deps", "--no-compile", wheel
      end
    end
    system python, "-m", "pip", "--python=#{libexec}/.venv/bin/python", "check"

    bash = formula_opt_bin("bash")/"bash"
    tmux_bin = formula_opt_bin("tmux")
    (bin/"pimux").write_env_script opt_libexec/"bin/pimux",
                                  PIMUX_BASH:    bash,
                                  PATH:          "#{bash.dirname}:#{tmux_bin}:$PATH",
                                  TERMINFO_DIRS: "#{Formula["ncurses"].opt_share}/terminfo:/usr/share/terminfo"
    inreplace libexec/"config/tmux.conf",
              'set -g @pimux_launcher "$HOME/.local/bin/pimux"',
              "set -g @pimux_launcher '#{opt_bin}/pimux'"
    inreplace libexec/"config/tmux.conf",
              'set -g default-command \'exec bash --rcfile "$HOME/.config/pimux/shell.bash" -i\'',
              "set -g default-command 'exec #{bash} --rcfile #{opt_libexec}/lib/shell.bash -i'"
  end

  def caveats
    <<~EOS
      This is the PiMux 1.0.0-beta.2 Mac foundation prerelease.
      Local terminal and multi-server CLI snapshots are available; remote session
      attachment/actions and a unified multi-server TUI are not implemented.
      No shell startup files or existing PiMux installation were changed.
      Use brew upgrade/uninstall pimux-preview to manage this package.
      Uninstall retains user settings, running sessions and remote key grants.
      A new tmux client does not upgrade already running tmux servers.
    EOS
  end

  test do
    ENV["HOME"] = testpath
    ENV["XDG_CONFIG_HOME"] = testpath/".config"
    ENV["TERM"] = "xterm-256color"
    ENV.delete "TMUX"
    ENV.delete "TMUX_PANE"
    sockets = testpath/"sockets"
    sockets.mkdir
    ENV["TMUX_TMPDIR"] = sockets
    assert_match "1.0.0-beta.2", shell_output("#{bin}/pimux --version")
    system libexec/".venv/bin/python", "-I", "-c", "import blessed, rich; print('runtime ready')"
    assert_match '"candidates": []', shell_output("#{bin}/pimux hosts discover --json")
    system bin/"pimux", "doctor"
    system bin/"pimux", "tmux", "new-session", "-d", "-s", "brew"
    system bin/"pimux", "tmux", "split-window", "-d", "-h", "-t", "brew"
    assert_equal "2", shell_output("#{bin}/pimux tmux list-panes -t brew -F '\#{pane_id}'").lines.count.to_s
    ready = ""
    50.times do
      ready = shell_output("#{bin}/pimux tmux show-options -pqv -t brew: @pimux_environment_ready").strip
      break if ready == "on"

      sleep 0.1
    end
    assert_equal "on", ready
    assert_match "Homebrew manages", shell_output("#{bin}/pimux uninstall 2>&1", 2)
    refute_path_exists testpath/".bashrc"
    refute_path_exists testpath/".zshrc"
    refute_path_exists testpath/".local/bin/pimux"
  ensure
    quiet_system bin/"pimux", "tmux", "kill-server" if sockets
    sockets&.rmtree
  end
end
