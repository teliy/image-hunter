"""Оффлайн-тест установщиков: find_python() из install.sh и диапазон install.ps1.

Реальный прогон find_python(): функция вырезается из install.sh и исполняется
bash'ем с подставными «python»-заглушками разных версий. Qt не нужен.

Запуск: python scripts/test_installers.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

BASH = shutil.which("bash") or "/bin/bash"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_fn(src: str, name: str) -> str:
    """Вырезать функцию name из install.sh (от «name() {» до одинокой «}»)."""
    lines = src.splitlines()
    out: list[str] = []
    on = False
    for ln in lines:
        if ln.startswith(name + "() {"):
            on = True
        if on:
            out.append(ln)
            if ln == "}":
                break
    if not out:
        raise AssertionError(f"функция {name} не найдена в install.sh")
    return "\n".join(out)


def make_stub(bin_dir: str, name: str, version: str) -> str:
    """Заглушка интерпретатора: на любой вызов печатает свою версию."""
    p = os.path.join(bin_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n")
        if version:
            f.write(f'printf \'{version}\\n\'\n')
    os.chmod(p, 0o755)
    return p


def make_runner(fn_text: str, call: str = "", prelude: str = "") -> str:
    runner = os.path.join(tempfile.mkdtemp(prefix="ih_runner_"), "runner.sh")
    with open(runner, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\nset -uo pipefail\n")
        f.write('warn() { printf "WARN: %s\\n" "$*" >&2; }\n')
        f.write('err()  { printf "ERR: %s\\n" "$*" >&2; }\n')
        f.write("SUDO=\"\"\n")
        if prelude:
            f.write(prelude + "\n")
        f.write(fn_text + "\n")
        if call:
            f.write(call + "\n")
    os.chmod(runner, 0o755)
    return runner


def run_find_python(bin_dir: str, env_extra: dict | None = None):
    """Запустить find_python с PATH=bin_dir; вернуть (stdout, stderr, rc)."""
    src = read(os.path.join(REPO, "install.sh"))
    runner = make_runner(extract_fn(src, "find_python"), call="find_python")
    env = dict(os.environ)
    # PATH = только папка заглушек: системные python3.x песочницы искажают тест
    env["PATH"] = bin_dir
    env.pop("IH_PYTHON", None)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([BASH, runner], capture_output=True, text=True,
                       env=env, timeout=30)
    return p.stdout.strip(), p.stderr.strip(), p.returncode


def main() -> int:
    sh_path = os.path.join(REPO, "install.sh")
    ps1_path = os.path.join(REPO, "install.ps1")
    sh = read(sh_path)
    ps1 = read(ps1_path)

    # 1. синтаксис
    rc = subprocess.run([BASH, "-n", sh_path]).returncode
    check("bash -n install.sh", rc == 0)

    # 2–8. реальный прогон find_python() с заглушками
    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b1:
        make_stub(b1, "python3.14", "3.14")
        out, err, rc = run_find_python(b1)
        check("python3.14 один — выбран (edge-Alpine)", out == "python3.14" and rc == 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b2:
        make_stub(b2, "python3", "3.12")
        out, err, rc = run_find_python(b2)
        check("python3 = 3.12 — выбран (stable-Alpine)", out == "python3" and rc == 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b3:
        make_stub(b3, "python3", "3.15")
        out, err, rc = run_find_python(b3)
        check("python3 = 3.15 — отклонён (вне диапазона)", out == "" and rc != 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b4:
        make_stub(b4, "python3", "3.9")
        out, err, rc = run_find_python(b4)
        check("python3 = 3.9 — отклонён (старый)", out == "" and rc != 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b5:
        make_stub(b5, "python3.13", "3.13")
        make_stub(b5, "python3", "3.14")
        out, err, rc = run_find_python(b5)
        check("при обоих выбрана отдельная версия 3.13", out == "python3.13" and rc == 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b6:
        make_stub(b6, "python3", "3.9")
        custom = make_stub(b6, "custom-python-3.11", "3.11")
        out, err, rc = run_find_python(b6, {"IH_PYTHON": custom})
        check("IH_PYTHON указан валидный 3.11 — принят", out == custom and rc == 0,
              f"out={out!r} rc={rc}")

    with tempfile.TemporaryDirectory(prefix="ih_stub_") as b7:
        make_stub(b7, "python3", "3.9")
        custom = make_stub(b7, "custom-old", "3.9")
        out, err, rc = run_find_python(b7, {"IH_PYTHON": custom})
        check("IH_PYTHON = 3.9 — отклонён с предупреждением",
              out == "" and rc != 0 and "не подходит" in err, f"out={out!r} err={err!r}")

    # 9. install.sh: apk (Alpine), gcompat, doas, shims для pip на musl
    check("install.sh: ветка apk с python3 + py3-pip",
          "apk add --no-cache python3 py3-pip" in sh)
    check("install.sh: gcompat/libstdc++ для musl",
          "apk add --no-cache gcompat libstdc++" in sh)
    check("install.sh: _manylinux.py разрешает glibc-колёса",
          "_manylinux.py" in sh and "manylinux_compatible" in sh)
    check("install.sh: поддержка doas", 'SUDO="doas"' in sh)
    check("install.sh: понятная ошибка pip на musl",
          "На musl (Alpine) у PySide6 нет нативных сборок" in sh)
    check("install.sh: есть is_musl/prepare_musl",
          "is_musl()" in sh and "prepare_musl()" in sh)

    # 10. install.ps1: диапазон 3.10–3.14
    check("install.ps1: -le 14 (3.14 принимается)", "-le 14" in ps1)
    check("install.ps1: старого -le 13 нет", "-le 13" not in ps1)
    check("install.ps1: текст «3.10–3.14»", "3.10–3.14" in ps1)
    check("install.ps1: winget ставит Python 3.12", "Python.Python.3.12" in ps1)

    # 11. реальный прогон prepare_musl(): пишет _manylinux.py в site-packages venv
    src = read(sh_path)
    prelude = "is_musl() { return 1; }   # в песочнице glibc: ветку apk пропускаем"
    venv = tempfile.mkdtemp(prefix="ih_venv_")
    site = tempfile.mkdtemp(prefix="ih_site_")
    os.makedirs(os.path.join(venv, "bin"), exist_ok=True)
    py = os.path.join(venv, "bin", "python")
    with open(py, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n")
        f.write(f'printf \'{site}\\n\'\n')   # sysconfig.get_paths()["purelib"]
    os.chmod(py, 0o755)
    runner = make_runner(extract_fn(src, "prepare_musl"),
                         call="prepare_musl '" + venv + "'", prelude=prelude)
    p = subprocess.run([BASH, runner, venv], capture_output=True, text=True, timeout=30)
    shim = os.path.join(site, "_manylinux.py")
    ok = p.returncode == 0 and os.path.isfile(shim) and "return True" in read(shim)
    check("prepare_musl: шим _manylinux.py записан в site-packages", ok,
          f"rc={p.returncode} err={p.stderr.strip()!r}")

    # 12. README ×3: диапазон обновлён везде, старого «3.10–3.13» нет
    for name in ("README.md", "README.en.md", "README.zh.md"):
        txt = read(os.path.join(REPO, name))
        check(f"{name}: 3.10–3.14 упомянут", "3.10–3.14" in txt)
        check(f"{name}: старого «3.10–3.13» нет", "3.10–3.13" not in txt)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
