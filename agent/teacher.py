"""本地出题老师入口。使用已登录的 Codex CLI，不要求另配 API 密钥。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_TOOL = ROOT / "math-question-teacher" / "scripts" / "library_tool.py"
LEVELS = ("简单", "中等", "较难", "拓展")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PAPER_SUFFIXES = IMAGE_SUFFIXES | {".pdf", ".docx"}


def existing_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"找不到文件：{path}")
    return path


def existing_image(value: str) -> Path:
    path = existing_file(value)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise argparse.ArgumentTypeError(f"图片应为 PNG、JPG 或 WEBP：{path}")
    return path


def existing_paper(value: str) -> Path:
    path = existing_file(value)
    if path.suffix.lower() not in PAPER_SUFFIXES:
        raise argparse.ArgumentTypeError("参考卷应为 PDF、DOCX、PNG、JPG 或 WEBP 文件")
    return path


def positive_count(value: str) -> int:
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError("题量必须大于 0")
    return count


def codex_command(prompt: str, images: list[Path], *, interactive: bool = False) -> list[str]:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 Codex CLI。请在已安装 Codex 的终端运行。")
    if interactive:
        command = [executable, "-C", str(ROOT)]
    else:
        command = [executable, "exec", "-C", str(ROOT), "--skip-git-repo-check",
                   "--sandbox", "workspace-write"]
    for path in images:
        command.extend(["-i", str(path)])
    if prompt:
        if images:
            command.append("--")
        command.append(prompt)
    return command


def run_codex(prompt: str, images: list[Path], args, *, interactive: bool = False) -> int:
    command = codex_command(prompt, images, interactive=interactive)
    if args.preview:
        print(json.dumps({"command": command, "workspace": str(ROOT)}, ensure_ascii=False, indent=2))
        return 0
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="出题老师：接收教材与试卷，按知识点出题，错题巩固，并按年级或参考卷组卷。"
    )
    parser.add_argument("--preview", action="store_true", help="只显示将运行的命令，不调用模型")
    sub = parser.add_subparsers(dest="action", required=True)

    chat = sub.add_parser("chat", help="打开与出题老师的交互会话")
    chat.add_argument("prompt", nargs="?", default="")
    chat.add_argument("--image", action="append", type=existing_image, default=[])

    ask = sub.add_parser("ask", help="发送一条自由提问")
    ask.add_argument("prompt")
    ask.add_argument("--image", action="append", type=existing_image, default=[])

    ingest = sub.add_parser("ingest", help="将教材或试卷加入资料库")
    ingest.add_argument("file", type=existing_file)
    ingest.add_argument("--kind", choices=("教材", "试卷"), required=True)
    ingest.add_argument("--edition", help="例如：人教A版高中数学必修第一册")
    ingest.add_argument("--scope", choices=("全量", "目录与题型"), default="全量")

    quiz = sub.add_parser("quiz", help="按知识点出题")
    quiz.add_argument("topic")
    quiz.add_argument("--count", type=positive_count, default=1,
                      help="常用题量：1、5、10、20；也接受其他正整数")
    quiz.add_argument("--level", choices=LEVELS, default="中等")
    quiz.add_argument("--book", help="教材或册次，例如：人教A版必修第一册")
    quiz.add_argument("--questions-only", action="store_true")

    mistake = sub.add_parser("mistake", help="根据错题出巩固题")
    mistake.add_argument("--image", action="append", type=existing_image, default=[])
    mistake.add_argument("--file", type=existing_file, help="PDF 等非图片文件")
    mistake.add_argument("--question", help="文字形式的原题")
    mistake.add_argument("--work", help="学生的答案或解题过程")
    mistake.add_argument("--count", type=positive_count, default=1)
    mistake.add_argument("--level", choices=LEVELS,
                         help="省略时保持与原题相近的难度")
    mistake.add_argument("--show-answers", action="store_true")

    paper = sub.add_parser("paper", help="按年级或参考试卷生成新试卷")
    paper.add_argument("--grade", help="目标年级，例如初二、高一；可与参考卷同时指定")
    paper.add_argument("--scope", help="学期、册次或章节范围，例如必修第一册第1章")
    paper.add_argument("--reference", action="append", type=existing_paper, default=[],
                       help="参考试卷文件，可重复传入多页图片或文档")
    paper.add_argument("--title", help="新试卷标题")
    paper.add_argument("--question-count", type=positive_count, help="总题量；省略时由范围或参考卷确定")
    paper.add_argument("--total-score", type=positive_count, help="满分；省略时由范围或参考卷确定")
    paper.add_argument("--duration", type=positive_count, help="考试时长，单位为分钟")
    paper.add_argument("--level", choices=LEVELS, help="整体难度")
    paper.add_argument("--questions-only", action="store_true", help="先只给学生试卷，不展示答案")

    sub.add_parser("status", help="查看资料库的实际入库进度")

    args = parser.parse_args()
    try:
        if args.action == "status":
            command = [sys.executable, str(LIBRARY_TOOL), "report"]
            if args.preview:
                print(json.dumps({"command": command}, ensure_ascii=False, indent=2))
                return 0
            return subprocess.run(command, cwd=ROOT, check=False).returncode
        if args.action == "chat":
            return run_codex(args.prompt, args.image, args, interactive=True)
        if args.action == "ask":
            return run_codex(args.prompt, args.image, args)
        if args.action == "ingest":
            details = f"；版本/册次：{args.edition}" if args.edition else ""
            prompt = (
                f"请按本项目出题老师的资料入库流程，把文件 {args.file} 作为{args.kind}入库"
                f"{details}。处理范围：{args.scope}。保存原件，检查重复，逐步提取与核对，"
                "持续更新资料库和进度；完成后给我准确的入库回执。"
            )
            images = [args.file] if args.file.suffix.lower() in IMAGE_SUFFIXES else []
            return run_codex(prompt, images, args)
        if args.action == "quiz":
            book = f"教材：{args.book}。" if args.book else ""
            answer_mode = "先只给题目，等我作答再给答案与解析。" if args.questions_only else "附答案与解析。"
            prompt = (f"{book}请围绕知识点“{args.topic}”出{args.count}道{args.level}练习题。"
                      f"{answer_mode}依据已入库的教材例题与习题，逐题验算。")
            return run_codex(prompt, [], args)
        if args.action == "mistake":
            if not args.image and not args.file and not args.question:
                parser.error("mistake 需要 --image、--file 或 --question")
            question = f"题目文字：{args.question}。" if args.question else ""
            if args.file:
                question += f"题目文件：{args.file}。"
            if args.image:
                question += "题目见附图。"
            work = f"我的作答：{args.work}。" if args.work else "暂未提供我的解题过程。"
            level = f"{args.level}难度" if args.level else "与原题相近的难度"
            answer_mode = "请立即给答案与解析。" if args.show_answers else "先只给新题，等我作答。"
            prompt = (
                f"{question}{work}请识别主知识点、题型与关键方法；有证据时判断第一处错误。"
                f"围绕同一方法出{args.count}道{level}巩固题，逐题验算。{answer_mode}"
            )
            return run_codex(prompt, args.image, args)
        if args.action == "paper":
            if not args.grade and not args.reference:
                parser.error("paper 需要 --grade 或至少一个 --reference")
            constraints = []
            for label, value in (("目标年级", args.grade), ("学期/册次/章节范围", args.scope),
                                 ("试卷标题", args.title), ("总题量", args.question_count),
                                 ("满分", args.total_score), ("考试时长（分钟）", args.duration),
                                 ("整体难度", args.level)):
                if value is not None:
                    constraints.append(f"{label}：{value}")
            references = "；".join(str(path) for path in args.reference)
            source = f"参考试卷：{references}。" if references else ""
            answer_mode = ("先只交付学生试卷，答案与解析暂不展示。" if args.questions_only
                           else "分开交付学生试卷与答案解析/评分参考。")
            prompt = (
                "请按本项目出题老师的组卷规则生成一套原创数学试卷。"
                f"{'；'.join(constraints)}。{source}"
                "先检查资料库的真实教材覆盖范围；如有参考卷，逐页识别其题型、题量、分值、"
                "知识点与难度，形成组卷蓝图。用户指定条件优先；按蓝图出新题，"
                "逐题独立验算，并核对题号与总分。"
                f"{answer_mode}注明教材依据的实际核对状态；参考卷仅作组卷参考，不自动入库。"
            )
            images = [path for path in args.reference if path.suffix.lower() in IMAGE_SUFFIXES]
            return run_codex(prompt, images, args)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
