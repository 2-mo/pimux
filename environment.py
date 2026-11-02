# pimux-managed: literal environment defaults for PiMux shells.
"""Store environment overrides without evaluating shell code."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

PROXY_NAMES = {"http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
SHELL_NAMES = {"HOME", "PATH", "SHELL", "TERM", "TMUX", "TMUX_PANE", "IFS", "ENV", "BASH_ENV",
               "PROMPT_COMMAND", "PS1", "PS2", "PS4", "PWD", "OLDPWD", "UID", "EUID", "PPID",
               "SHELLOPTS", "BASHOPTS", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "SHLVL",
               "PS0", "RANDOM", "SRANDOM", "SECONDS", "LINENO", "HISTCMD", "OPTARG", "OPTIND",
               "DIRSTACK", "FUNCNAME", "GROUPS", "PIPESTATUS", "_"}


def tr(english, chinese):
    return chinese if os.environ.get("PIMUX_LANGUAGE") == "zh" else english


def editable(name):
    return (bool(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name)) and name not in SHELL_NAMES
            and name not in PROXY_NAMES and not name.startswith(("PIMUX_", "BASH", "CONDA_")))


def validate_name(name):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError(tr("Use letters, digits and underscores; do not start with a digit.",
                            "变量名只能包含字母、数字和下划线，不能以数字开头。"))
    if name in PROXY_NAMES:
        raise ValueError(tr("Use the Network proxy entry to manage proxy addresses.", "请通过“网络代理”入口管理代理地址。"))
    if not editable(name):
        raise ValueError(tr("This variable is maintained by the shell or environment tools.",
                            "这个变量由 shell 或环境工具维护，可查看，不能在这里覆盖。"))


def config_path():
    return Path(os.environ.get("PIMUX_ENV_FILE", str(Path.home() / ".config/pimux/environment.json")))


def read_settings():
    try:
        data = json.loads(config_path().read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise RuntimeError(tr("Could not read environment settings.", "无法读取环境变量设置。")) from None
    if not isinstance(data, dict):
        raise RuntimeError(tr("Invalid environment settings.", "环境变量设置格式无效。"))
    for name, record in data.items():
        if (not editable(name) or not isinstance(record, dict) or set(record) != {"enabled", "value"}
                or not isinstance(record["enabled"], bool) or not isinstance(record["value"], str)
                or "\0" in record["value"]):
            raise RuntimeError(tr("Invalid environment settings.", "环境变量设置格式无效。"))
    return data


def change(name, action, value=None):
    validate_name(name)
    if action == "set" and not isinstance(value, str):
        raise ValueError(tr("Set a value first.", "请先设置这个变量的值。"))
    if value is not None and "\0" in value:
        raise ValueError(tr("Environment values cannot contain a NUL character.", "变量值不能包含 NUL 字符。"))
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_settings()
        if action == "reset":
            data.pop(name, None)
        elif action == "set":
            data[name] = {"enabled": True, "value": value}
        elif action in {"on", "off"}:
            if name not in data:
                if value is None:
                    raise ValueError(tr("Set a value first.", "请先设置这个变量的值。"))
                data[name] = {"enabled": action == "on", "value": value}
            else:
                data[name]["enabled"] = action == "on"
        else:
            raise ValueError("Unknown environment action")
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(data, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def secret(name):
    return bool(re.search(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|CREDENTIAL|AUTH|COOKIE", name, re.I))


def display_value(name, value, *, reveal=False):
    if not reveal:
        if secret(name) and value:
            return "••••••••"
        value = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s]*@", r"\1***@", value)
    value = value.replace("\n", "↵").replace("\t", "⇥")
    return re.sub(r"[\x00-\x1f\x7f]", "?", value)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["__emit"]:
        try:
            data = read_settings()
        except RuntimeError:
            return 1
        records = ["PIMUX_ENV_V1"]
        for name, record in sorted(data.items()):
            records.extend((name, "on" if record["enabled"] else "off", record["value"]))
        sys.stdout.buffer.write(("\0".join(records) + "\0").encode())
        return 0
    parser = argparse.ArgumentParser(prog="pimux env")
    parser.add_argument("action", nargs="?", default="show", choices=["show", "set", "on", "off", "reset"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("value", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.action == "show":
            if args.value is not None:
                parser.error("pimux env show [query]")
            data = read_settings()
            print(tr("PiMux · Environment defaults", "PiMux · 默认环境变量"))
            for name in sorted(set(os.environ) | set(data), key=lambda key: (key not in data, key)):
                if args.name and args.name.casefold() not in name.casefold():
                    continue
                record = data.get(name)
                state = (tr("set", "设置") if record["enabled"] else tr("off", "停用")) if record else tr("inherited", "继承")
                value = record["value"] if record else os.environ[name]
                print(f"{name}  [{state}]  {display_value(name, value)}")
        else:
            if not args.name or (args.action == "set") != (args.value is not None):
                parser.error("pimux env set NAME VALUE | on/off/reset NAME")
            value = os.environ.get(args.name, "") if args.action == "off" else args.value
            change(args.name, args.action, value)
            print(tr("Saved · new PiMux windows apply it automatically; integrated shells apply at the next prompt.",
                     "已保存 · 新 PiMux 窗口自动应用，已集成的 shell 在下次提示符应用。"))
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
