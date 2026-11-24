"""Maintain the local question-teacher library; semantic reading stays with the agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SKILL_ROOT = Path(__file__).resolve().parents[1]
DIFFICULTIES = {"简单", "中等", "较难", "拓展", "待定"}
ITEM_STATUSES = {"parsed", "answer_verified", "needs_review", "open_ended"}


def library_root() -> Path:
    config = json.loads((SKILL_ROOT / "config.json").read_text(encoding="utf-8"))
    configured = Path(os.environ.get("QUESTION_TEACHER_LIBRARY_ROOT", config["library_root"])).expanduser()
    root = (configured if configured.is_absolute() else SKILL_ROOT / configured).resolve()
    if not root.is_dir():
        raise ValueError(f"Library does not exist: {root}")
    return root


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, value) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_pages(path: Path) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except ImportError:
        result = subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True, check=False
        )
        match = re.search(r"^Pages:\s*(\d+)", result.stdout, re.MULTILINE)
        return int(match.group(1)) if match else None


def source_records(root: Path):
    return read_json(root / "data" / "source-register.json")["sources"]


def catalog_sections(root: Path) -> set[str]:
    sections = set()
    for path in (root / "data" / "catalogs").glob("*.json"):
        catalog = read_json(path)
        source_id = catalog["source_id"]
        sections.update(
            f"{source_id}:{section['id']}"
            for chapter in catalog["chapters"]
            for section in chapter["sections"]
        )
    return sections


def add_source(args) -> None:
    root = library_root()
    src = Path(args.file).expanduser().resolve(strict=True)
    if not src.is_file():
        raise ValueError(f"Not a file: {src}")
    digest = sha256(src)
    registry_path = root / "data" / "source-register.json"
    registry = read_json(registry_path)
    for entry in registry["sources"]:
        if entry["sha256"] == digest:
            print(json.dumps({"result": "duplicate", "source_id": entry["id"]}, ensure_ascii=False))
            return
    source_id = args.id or f"source-{digest[:12]}"
    if any(entry["id"] == source_id for entry in registry["sources"]):
        raise ValueError(f"Source ID already exists: {source_id}")
    suffix = src.suffix.lower()
    dest_rel = Path("sources") / f"{source_id}{suffix}"
    dest = root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copy2(src, tmp)
    if sha256(tmp) != digest:
        tmp.unlink()
        raise ValueError("Copy checksum mismatch")
    os.replace(tmp, dest)
    entry = {
        "id": source_id,
        "kind": args.kind,
        "title": args.title or src.stem,
        "original_filename": src.name,
        "edition": args.edition or "待确认",
        "imported_at": date.today().isoformat(),
        "file": dest_rel.as_posix(),
        "sha256": digest,
        "pdf_pages": pdf_pages(dest) if suffix == ".pdf" else None,
        "status": "file_saved",
        "coverage": {
            "catalog": "not_indexed",
            "section_notes": [],
            "textbook_questions": "not_indexed",
            "answers": "not_verified",
        },
        "progress": {"stage": "file_saved", "next_pdf_page": 1},
    }
    registry["sources"].append(entry)
    write_json(registry_path, registry)
    print(json.dumps({"result": "added", "source_id": source_id, "file": str(dest)}, ensure_ascii=False))


def load_items(path: Path) -> list[dict]:
    items = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return items


def validate_item(item: dict, sources: dict[str, dict], sections: set[str]) -> None:
    required = {"id", "source_id", "location", "section_ids", "type",
                "method", "difficulty", "question", "answer", "status"}
    missing = required - set(item)
    if missing:
        raise ValueError(f"{item.get('id', '<no id>')}: missing {sorted(missing)}")
    if not isinstance(item["id"], str) or not item["id"]:
        raise ValueError("Item ID must be a nonempty string")
    if item["source_id"] not in sources:
        raise ValueError(f"{item['id']}: unknown source {item['source_id']}")
    if not isinstance(item["section_ids"], list):
        raise ValueError(f"{item['id']}: section_ids must be a list")
    if not item["section_ids"] and item["status"] != "needs_review":
        raise ValueError(f"{item['id']}: unclassified items must be needs_review")
    unknown = set(item["section_ids"]) - sections
    if unknown:
        raise ValueError(f"{item['id']}: unknown sections {sorted(unknown)}")
    if item["difficulty"] not in DIFFICULTIES:
        raise ValueError(f"{item['id']}: invalid difficulty")
    if item["status"] not in ITEM_STATUSES:
        raise ValueError(f"{item['id']}: invalid status")
    if item["status"] == "answer_verified" and not item["answer"]:
        raise ValueError(f"{item['id']}: verified answer is empty")
    if not isinstance(item["location"], dict) or not any(
        item["location"].get(key) for key in ("pdf_page", "page", "image", "line", "label")
    ):
        raise ValueError(f"{item['id']}: missing source location")
    if "pdf_page" in item["location"]:
        pdf_page = item["location"]["pdf_page"]
        page_count = sources[item["source_id"]].get("pdf_pages")
        if not isinstance(pdf_page, int) or pdf_page < 1 or (page_count and pdf_page > page_count):
            raise ValueError(f"{item['id']}: PDF page out of range")
    if not isinstance(item["question"], str) or not item["question"].strip():
        raise ValueError(f"{item['id']}: empty question")


def upsert_items(args) -> None:
    root = library_root()
    bank_path = root / "data" / "question-bank.jsonl"
    registry_path = root / "data" / "source-register.json"
    registry = read_json(registry_path)
    source_map = {entry["id"]: entry for entry in registry["sources"]}
    sections = catalog_sections(root)
    existing = {item["id"]: item for item in load_items(bank_path)}
    incoming = load_items(Path(args.input))
    if len({item.get("id") for item in incoming}) != len(incoming):
        raise ValueError("Duplicate IDs in incoming items")
    added = updated = 0
    for item in incoming:
        validate_item(item, source_map, sections)
        old = existing.get(item["id"])
        if old is None:
            added += 1
        elif old != item:
            updated += 1
        existing[item["id"]] = item
    content = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing.values())
    atomic_write(bank_path, content)
    for entry in registry["sources"]:
        related = [item for item in existing.values() if item["source_id"] == entry["id"]]
        entry.setdefault("coverage", {})["items_indexed"] = len(related)
        entry["coverage"]["answers_verified"] = sum(item["status"] == "answer_verified" for item in related)
        entry["coverage"]["open_ended_items"] = sum(item["status"] == "open_ended" for item in related)
        if related and entry["status"] == "file_saved":
            entry["status"] = "partial_ingest"
    write_json(registry_path, registry)
    print(json.dumps({"added": added, "updated": updated, "total": len(existing)}, ensure_ascii=False))


def validate(args) -> None:
    root = library_root()
    sources = source_records(root)
    ids = [entry["id"] for entry in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source IDs")
    for entry in sources:
        path = root / entry["file"]
        if not path.is_file():
            raise ValueError(f"Missing source: {entry['id']}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Checksum mismatch: {entry['id']}")
        progress = entry.get("progress")
        if progress and entry.get("pdf_pages"):
            next_page = progress.get("next_pdf_page")
            if not isinstance(next_page, int) or not 1 <= next_page <= entry["pdf_pages"] + 1:
                raise ValueError(f"Invalid progress page: {entry['id']}")
    catalog_paths = list((root / "data" / "catalogs").glob("*.json"))
    for path in catalog_paths:
        catalog = read_json(path)
        if catalog["source_id"] not in ids:
            raise ValueError(f"Catalog source is unregistered: {path}")
        section_ids = [section["id"] for chapter in catalog["chapters"] for section in chapter["sections"]]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError(f"Duplicate section IDs: {path}")
    sections = catalog_sections(root)
    items = load_items(root / "data" / "question-bank.jsonl")
    item_ids = [item["id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("Duplicate item IDs")
    for item in items:
        validate_item(item, {entry["id"]: entry for entry in sources}, sections)
    for entry in sources:
        coverage = entry.get("coverage", {})
        source_items = [item for item in items if item["source_id"] == entry["id"]]
        if "items_indexed" in coverage and coverage["items_indexed"] != len(source_items):
            raise ValueError(f"Item count mismatch: {entry['id']}")
        verified = sum(item["status"] == "answer_verified" for item in source_items)
        if "answers_verified" in coverage and coverage["answers_verified"] != verified:
            raise ValueError(f"Verified answer count mismatch: {entry['id']}")
    exam_indexes = list((root / "data" / "exam-index").glob("*.json"))
    source_ids = set(ids)
    item_id_set = set(item_ids)
    for index_path in exam_indexes:
        index = read_json(index_path)
        districts = index.get("districts", [])
        names = [district["district"] for district in districts]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate districts: {index_path}")
        referenced_files = 0
        reviewed = 0
        for district in districts:
            if district.get("primary_source_id") not in source_ids:
                raise ValueError(f"Unknown primary exam source: {district['district']}")
            for linked in district.get("files", []):
                if linked["source_id"] not in source_ids:
                    raise ValueError(f"Unknown linked exam source: {linked['source_id']}")
                referenced_files += 1
            for question_id in district.get("reviewed_questions", []):
                if question_id not in item_id_set:
                    raise ValueError(f"Unknown reviewed exam item: {question_id}")
                reviewed += 1
        if "source_file_count" in index and index["source_file_count"] != referenced_files:
            raise ValueError(f"Exam source file count mismatch: {index_path}")
        if "question_bank_item_count" in index and index["question_bank_item_count"] != reviewed:
            raise ValueError(f"Exam reviewed item count mismatch: {index_path}")
    print(json.dumps({"valid": True, "sources": len(sources), "sections": len(sections),
                      "items": len(items)}, ensure_ascii=False))


def report(args) -> None:
    root = library_root()
    sources = source_records(root)
    items = load_items(root / "data" / "question-bank.jsonl")
    by_status = Counter(item["status"] for item in items)
    by_section = Counter(section for item in items for section in item["section_ids"])
    exam_collections = []
    for path in (root / "data" / "exam-index").glob("*.json"):
        index = read_json(path)
        exam_collections.append({"id": index["collection_id"],
                                 "districts": len(index.get("districts", [])),
                                 "files": index.get("source_file_count"),
                                 "reviewed_items": index.get("question_bank_item_count", 0),
                                 "stage": index.get("stage")})
    print(json.dumps({
        "source_count": len(sources),
        "sources_by_kind": Counter(entry["kind"] for entry in sources),
        "exam_collections": exam_collections,
        "sources": [{"id": entry["id"], "status": entry["status"],
                     "coverage": entry.get("coverage", {}),
                     "progress": entry.get("progress")} for entry in sources],
        "items": len(items),
        "item_statuses": by_status,
        "items_by_section": by_section,
    }, ensure_ascii=False, indent=2))


def mark_progress(args) -> None:
    root = library_root()
    path = root / "data" / "source-register.json"
    registry = read_json(path)
    entry = next((source for source in registry["sources"] if source["id"] == args.source_id), None)
    if entry is None:
        raise ValueError(f"Unknown source: {args.source_id}")
    if args.next_page < 1 or (
        entry.get("pdf_pages") and args.next_page > entry["pdf_pages"] + 1
    ):
        raise ValueError("Progress page out of range")
    entry["progress"] = {"stage": args.stage, "next_pdf_page": args.next_page,
                         "note": args.note or ""}
    write_json(path, registry)
    print(json.dumps({"source_id": args.source_id, "progress": entry["progress"]}, ensure_ascii=False))


def render_pages(args) -> None:
    root = library_root()
    entry = next((source for source in source_records(root) if source["id"] == args.source_id), None)
    if entry is None:
        raise ValueError(f"Unknown source: {args.source_id}")
    source = root / entry["file"]
    if source.suffix.lower() != ".pdf":
        raise ValueError("Source is not PDF")
    if args.first < 1 or args.last < args.first or (
        entry.get("pdf_pages") and args.last > entry["pdf_pages"]
    ):
        raise ValueError("Invalid page range")
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    for page in range(args.first, args.last + 1):
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page),
                        "-singlefile", "-scale-to", str(args.size), "-png",
                        str(source), str(output / f"{args.source_id}-p{page:03d}")],
                       check=True)
    print(json.dumps({"rendered_pages": args.last - args.first + 1,
                      "output": str(output)}, ensure_ascii=False))


def extract_pages(args) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf is required for text extraction") from exc
    root = library_root()
    entry = next((source for source in source_records(root) if source["id"] == args.source_id), None)
    if entry is None:
        raise ValueError(f"Unknown source: {args.source_id}")
    source = root / entry["file"]
    if source.suffix.lower() != ".pdf":
        raise ValueError("Source is not PDF")
    reader = PdfReader(source)
    if args.first < 1 or args.last < args.first or args.last > len(reader.pages):
        raise ValueError("Invalid page range")
    rows = []
    for page in range(args.first, args.last + 1):
        rows.append({"source_id": args.source_id, "pdf_page": page,
                     "text": reader.pages[page - 1].extract_text() or ""})
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    print(json.dumps({"pages": len(rows), "with_text": sum(bool(row["text"].strip()) for row in rows),
                      "output": str(output)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-source")
    add.add_argument("--file", required=True)
    add.add_argument("--kind", choices=["textbook", "exam", "other"], required=True)
    add.add_argument("--title")
    add.add_argument("--edition")
    add.add_argument("--id")
    add.set_defaults(func=add_source)
    upsert = sub.add_parser("upsert-items")
    upsert.add_argument("--input", required=True, help="JSONL file with reviewed item records")
    upsert.set_defaults(func=upsert_items)
    check = sub.add_parser("validate")
    check.set_defaults(func=validate)
    status = sub.add_parser("report")
    status.set_defaults(func=report)
    progress = sub.add_parser("mark-progress")
    progress.add_argument("--source-id", required=True)
    progress.add_argument("--stage", required=True)
    progress.add_argument("--next-page", type=int, required=True)
    progress.add_argument("--note")
    progress.set_defaults(func=mark_progress)
    render = sub.add_parser("render-pages")
    render.add_argument("--source-id", required=True)
    render.add_argument("--first", type=int, required=True)
    render.add_argument("--last", type=int, required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--size", type=int, default=1800)
    render.set_defaults(func=render_pages)
    extract = sub.add_parser("extract-pages")
    extract.add_argument("--source-id", required=True)
    extract.add_argument("--first", type=int, required=True)
    extract.add_argument("--last", type=int, required=True)
    extract.add_argument("--output", required=True)
    extract.set_defaults(func=extract_pages)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
