from __future__ import annotations

"""从现有素材重建经济页 GUI、本地化，并可选生成完整安装包。"""

import argparse
import re
import runpy
import zipfile
from pathlib import Path


SRC = Path(__file__).resolve().parent
MOD = SRC.parent
BEGIN = "# GCD_INSERT_BEGIN"
END = "# GCD_INSERT_END"


def named_window_bounds(source: str, name: str) -> tuple[int, int]:
    """定位指定 windowType；忽略字符串和注释中的括号。"""
    for match in re.finditer(r"\bwindowType\s*=\s*\{", source):
        opening = source.index("{", match.start())
        header = re.match(r'\s*name\s*=\s*"?([\w]+)"?', source[opening + 1 :])
        if not header or header[1] != name:
            continue
        depth = 0
        quoted = comment = escaped = False
        for index in range(opening, len(source)):
            char = source[index]
            if comment:
                comment = char != "\n"
                continue
            if escaped:
                escaped = False
                continue
            if quoted and char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                if char == "#":
                    comment = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return match.start(), index + 1
        raise ValueError(f"窗口 {name} 的括号不完整")
    raise ValueError(f"未找到窗口 {name}")


def build_gui(base_path: Path) -> Path:
    base = base_path.read_bytes().decode("latin1")
    if BEGIN in base or "gcd_gui_open" in base:
        raise ValueError("基础文件已包含城市 UI，请使用未插入城市 UI 的经济界面文件")
    fragment = (SRC / "经济界面_窗口片段.txt").read_text(encoding="utf-8-sig")
    if not fragment.isascii() or fragment.count(BEGIN) != 1 or fragment.count(END) != 1:
        raise ValueError("窗口片段应为 ASCII，且只包含一对 GCD 插入标记")
    _, window_end = named_window_bounds(base, "countryeconomyview")
    newline = "\r\n" if "\r\n" in base else "\n"
    insertion = newline + fragment.strip().replace("\n", newline) + newline
    result = base[: window_end - 1] + insertion + base[window_end - 1 :]
    target = MOD / "interface" / "countryeconomyview.gui"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.encode("latin1"))
    return target


def build_localisation() -> list[Path]:
    convert_file = runpy.run_path(str(SRC / "EU4本地化转码.py"))["convert_file"]
    # 新增：统一重建城市、任务与改革本地化，避免修改中文原文后漏更新游戏文件。
    sources = {
        "城市发展署_中文原文.yml": "gcd_city_bureau_l_english.yml",
        "加韦德任务_中文原文.yml": "gawed_stage1_l_english.yml",
        "威利亚姆改革_中文原文.yml": "gcd_welyam_reform_l_english.yml",
        "永冻边区事件_中文原文.yml": "gcd_yongdongbianqu_l_english.yml",
        "加韦德君主制_中文原文.yml": "gcd_gawedi_monarchy_l_english.yml",
        "王冠与婚约_中文原文.yml": "gcd_royal_marriage_l_english.yml",
    }
    targets = []
    for source, name in sources.items():
        target = MOD / "localisation" / name
        convert_file(SRC / source, target)
        targets.append(target)
    return targets


def package(destination: Path) -> None:
    destination = destination.resolve()
    if destination.is_relative_to(MOD.resolve()):
        raise ValueError("压缩包请输出到模组目录以外")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(MOD.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                archive.write(file, Path(MOD.name) / file.relative_to(MOD))
        descriptor = (MOD / "descriptor.mod").read_text(encoding="utf-8-sig")
        descriptor = re.sub(r'^path\s*=.*\n?', "", descriptor, flags=re.MULTILINE)
        archive.writestr(f"{MOD.name}.mod", descriptor.rstrip() + f'\npath="mod/{MOD.name}"\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--economy-base", type=Path, default=SRC / "经济界面_基础文件.txt",
                        help="可选：从当前游戏或兼容模组的经济 GUI 重新合并")
    parser.add_argument("--zip", type=Path, help="可选：输出包含文件夹和外部 .mod 的安装包")
    args = parser.parse_args()
    # 防止从旧版本混装时继续覆盖决议页或恢复决议入口。
    legacy = [MOD / "interface" / "countrydecisionsview.gui",
              MOD / "decisions" / "gcd_city_bureau.txt"]
    for file in legacy:
        if file.exists():
            raise SystemExit(f"请先备份并移除旧经济页迁移前文件：{file}")
    print(build_gui(args.economy_base))
    for target in build_localisation():
        print(target)
    # 修正（加载）：打包前检查实际文件字节，普通脚本不能混用本地化的 BOM 编码。
    check_path = MOD / "tools" / "check_encoding.py"
    if check_path.exists():
        problems = runpy.run_path(str(check_path))["errors"](MOD)
        if problems:
            raise SystemExit("\n".join(problems))
    if args.zip:
        package(args.zip)
        print(args.zip.resolve())


if __name__ == "__main__":
    main()
