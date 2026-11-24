#!/usr/bin/env bash
# tiktok-cli installer — curl | bash
# Installs the `tiktok` command via uv (preferred), pipx, or pip --user.
set -euo pipefail
umask 022

# === Config ===
PACKAGE="tiktok-cli"
BIN_NAME="tiktok"
OWNER="quangdang46"
REPO="tiktok_cli"
GIT_URL="https://github.com/${OWNER}/${REPO}.git"
PYPI_SPEC="${PACKAGE}"          # falls back to PyPI once published
QUIET=0
VERIFY=0
UNINSTALL=0
WITH_MLX=0                      # install the [mlx] extra on Apple Silicon
PREFER=""                       # uv | pipx | pip | auto
VERSION=""                      # pin: git tag/branch/commit or version spec
MAX_RETRIES=3
LOCK_DIR="/tmp/tiktok-cli-install.lock.d"
TMP=""

# === Logging ===
log_info()    { [ "$QUIET" -eq 1 ] && return; echo "[tiktok-cli] $*" >&2; }
log_warn()    { echo "[tiktok-cli] WARN: $*" >&2; }
log_success() { [ "$QUIET" -eq 1 ] && return; echo "✓ $*" >&2; }
die()         { echo "ERROR: $*" >&2; exit 1; }

# === Cleanup & lock ===
cleanup() { rm -rf "$TMP" "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"
        return 0
    fi
    die "Another install is running. If stuck: rm -rf $LOCK_DIR"
}

usage() {
    cat >&2 <<'EOF'
Usage: install.sh [options]

  --version VERSION   Pin version (git ref or spec, e.g. v0.1.0)
  --prefer METHOD     uv | pipx | pip (default: auto-detect)
  --with-mlx          Install the [mlx] extra (Apple Silicon Whisper backend)
  --verify            Run `tiktok --help` after install
  --uninstall         Remove tiktok-cli
  --quiet, -q         Less output
  -h, --help          This help
EOF
    exit 0
}

# === Args (support --flag value and --flag=value) ===
while [ $# -gt 0 ]; do
    case "$1" in
        --version)    VERSION="${2:-}"; shift 2;;
        --version=*)  VERSION="${1#*=}"; shift;;
        --prefer)     PREFER="${2:-}"; shift 2;;
        --prefer=*)   PREFER="${1#*=}"; shift;;
        --with-mlx)   WITH_MLX=1; shift;;
        --verify)     VERIFY=1; shift;;
        --uninstall)  UNINSTALL=1; shift;;
        --quiet|-q)   QUIET=1; shift;;
        -h|--help)    usage;;
        *)            log_warn "unknown arg: $1"; shift;;
    esac
done

# === Spec resolution ===
# Priority: explicit --version > git repo @ ref > PyPI name.
spec_for() {
    local method="$1"
    if [ -n "$VERSION" ]; then
        # Accept bare versions (0.1.0 -> v0.1.0) or full git refs.
        case "$VERSION" in
            v*|http*|git*|/*) echo "git+${GIT_URL}@${VERSION}" ;;
            *)                echo "${GIT_URL}@${VERSION}" ;;
        esac
    else
        echo "git+${GIT_URL}"
    fi
}

# === Python sanity ===
have_python() {
    command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null
}

# === Install methods ===
install_uv() {
    command -v uv >/dev/null 2>&1 || return 1
    local spec; spec=$(spec_for uv)
    local extra=""; [ "$WITH_MLX" -eq 1 ] && extra="[mlx]"
    log_info "Installing via uv tool: ${spec}${extra}"
    uv tool install --force "${spec}${extra}" --python '>=3.11'
}

install_pipx() {
    command -v pipx >/dev/null 2>&1 || return 1
    local spec; spec=$(spec_for pipx)
    local extra=""; [ "$WITH_MLX" -eq 1 ] && extra="[mlx]"
    log_info "Installing via pipx: ${spec}${extra}"
    pipx install --force "${spec}${extra}"
}

install_pip_user() {
    have_python || die "Python 3.11+ not found. Install Python first: https://www.python.org/downloads/ or use 'brew install python uv'"
    local spec; spec=$(spec_for pip)
    local extra=""; [ "$WITH_MLX" -eq 1 ] && extra="[mlx]"
    log_info "Installing via pip --user: ${spec}${extra}"
    python3 -m pip install --user --upgrade "${spec}${extra}"
    warn_pip_user_path
}

warn_pip_user_path() {
    local scripts_dir
    scripts_dir=$(python3 -c 'import site,sys; print(site.getusersitepackages().rsplit("/lib",1)[0] + "/bin")' 2>/dev/null || true)
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) log_warn "~/.local/bin may not be on PATH. Add it or use uv/pipx instead." ;;
    esac
}

# === Uninstall ===
do_uninstall() {
    if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q "^${PACKAGE}"; then
        uv tool uninstall "$PACKAGE" && log_success "uninstalled via uv"
    elif command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "$PACKAGE"; then
        pipx uninstall "$PACKAGE" && log_success "uninstalled via pipx"
    elif have_python; then
        python3 -m pip uninstall -y "$PACKAGE" 2>/dev/null && log_success "uninstalled via pip" || true
    fi
    command -v "$BIN_NAME" >/dev/null 2>&1 && log_warn "$BIN_NAME still resolves on PATH — check for a stale copy"
    log_success "done"
    exit 0
}

# === Verify ===
verify_install() {
    hash -r 2>/dev/null || true
    local bin; bin=$(command -v "$BIN_NAME" 2>/dev/null || true)
    [ -n "$bin" ] || die "$BIN_NAME not found on PATH after install"
    log_info "$BIN_NAME -> $bin"
    "$bin" --help >/dev/null 2>&1 || die "$bin --help failed"
    "$bin" --version 2>/dev/null || true
}

# === Main ===
main() {
    if [ "$UNINSTALL" -eq 1 ]; then do_uninstall; fi
    acquire_lock
    TMP=$(mktemp -d)

    # Pick method
    local method="$PREFER"
    if [ -z "$method" ] || [ "$method" = "auto" ]; then
        if command -v uv >/dev/null 2>&1; then method="uv"
        elif command -v pipx >/dev/null 2>&1; then method="pipx"
        elif have_python; then method="pip"
        else die "No installer found. Install uv (recommended): curl -LsSf https://astral.sh/uv/install.sh | sh"
        fi
    fi
    log_info "Method: $method | Package: $PACKAGE"

    local ok=0
    case "$method" in
        uv)    install_uv    && ok=1 || log_warn "uv install failed";;
        pipx)  install_pipx  && ok=1 || log_warn "pipx install failed";;
        pip)   install_pip_user && ok=1 || log_warn "pip install failed";;
        *)     die "Unknown --prefer method: $method (uv|pipx|pip)";;
    esac

    if [ "$ok" -eq 0 ]; then
        # Fallback chain: try the others before giving up
        log_warn "Trying fallback installers..."
        install_uv && ok=1 || install_pipx && ok=1 || install_pip_user && ok=1 || die "All install methods failed"
    fi

    [ "$VERIFY" -eq 1 ] && verify_install
    [ "$VERIFY" -eq 0 ] && hash -r 2>/dev/null || true

    echo ""
    log_success "$BIN_NAME installed"
    echo "  Run: $BIN_NAME --help"
    echo "  Verify: $BIN_NAME doctor"
}

# curl|bash safety: buffer entire script before executing
if [[ "${BASH_SOURCE[0]:-}" == "${0:-}" ]] || [[ -z "${BASH_SOURCE[0]:-}" ]]; then
    { main "$@"; }
fi
