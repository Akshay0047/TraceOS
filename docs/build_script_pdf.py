"""Write docs/two-minute-script.pdf. Run from the repository root."""

from pathlib import Path


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = word if not current else f"{current} {word}"
        if len(trial) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


SECTIONS = [
    (
        "Existing systems",
        "System monitors show CPU and memory at one instant, then forget them. A slow leak, "
        "a spawn storm, or rising disk use never becomes a history. Algorithm simulators run "
        "FCFS, paging, and deadlock examples correctly, but only on numbers typed in by hand. "
        "Learning models inside eBPF are fast, and they target networks and security. They do "
        "not name a scheduling or paging decision, and they do not replay a captured trace.",
    ),
    (
        "Proposed system",
        "Trace OS is one pipeline on one trace. Observe a window of real signals. Detect the "
        "workload. Explain it with the operating-system concept behind it. Replay that same "
        "trace through classical algorithms, and write the comparison down. The aim is teaching. "
        "The demo needs no network and no language model.",
    ),
    (
        "Implementation",
        "Observation uses psutil on Windows and on Linux. Once a second it records CPU, memory, "
        "process births, disk bytes, tasks actually executing, page faults, and context switches. "
        "One system snapshot counts those executing tasks, so the window does not open every "
        "process. These numbers are not the kernel run queue and not the page tables. "
        "Detection is a depth-limited decision tree trained on synthetic windows: normal, CPU "
        "saturation, memory growth, a spawn storm, or heavy I/O. One tree ships so the splits "
        "can be read aloud. Each detection has a confidence score, and an isolation forest marks "
        "a window unlike those five classes. The path is named CPU scheduling, memory and paging, "
        "process creation, or blocking I/O. Each window becomes a job and each sample a page id. "
        "FCFS, SJF, SRTF, priority, and round robin run beside FIFO, LRU, and optimal, on that "
        "same trace. The dashboard shows the Gantt chart and the fault counts. Frames and the "
        "round-robin quantum rerun the tables. The lab can peg the CPUs, climb memory, start a "
        "few processes, write a file, or collide two lock orders and give up. The report exports "
        "as Markdown or HTML.",
    ),
    (
        "Left out on purpose",
        "eBPF, a local language model, Banker's algorithm, and cgroups are not in this build. "
        "Random forests and XGBoost were proposed. The readable tree is what shipped, so the "
        "explanation stays the path the model actually took.",
    ),
]


def spoken_words() -> int:
    return len(" ".join(paragraph for _title, paragraph in SECTIONS).split())


def build(path: Path) -> None:
    blocks: list[tuple[str, bool]] = [
        ("Trace OS", True),
        ("Two-minute speaking script", True),
        (
            "Read this at a steady pace. It covers existing systems, the proposed pipeline, "
            "and what is implemented.",
            False,
        ),
    ]
    for title, paragraph in SECTIONS:
        blocks.append((title, True))
        blocks.append((paragraph, False))

    page_w, page_h = 612, 792
    left, top, bottom = 54, 740, 54
    pages: list[list[tuple[str, int, int, bool]]] = [[]]
    y = top

    def add(line: str, size: int, leading: int, heading: bool) -> None:
        nonlocal y
        if y - leading < bottom:
            pages.append([])
            y = top
        pages[-1].append((line, size, y, heading))
        y -= leading

    for text, heading in blocks:
        size = 16 if text == "Trace OS" else (13 if heading else 11)
        leading = 22 if text == "Trace OS" else (18 if heading else 15)
        if heading and text not in {"Trace OS", "Two-minute speaking script"}:
            y -= 6
        width = 78 if heading else 92
        for line in wrap(text, width):
            add(line, size, leading, heading)
        y -= 2

    objects: list[bytes | str] = []

    def add_obj(data: bytes | str) -> int:
        objects.append(data)
        return len(objects)

    font = add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    content_ids = []
    for page in pages:
        commands = ["BT"]
        for line, size, yy, heading in page:
            face = "/F2" if heading else "/F1"
            commands.append(f"{face} {size} Tf")
            commands.append(f"1 0 0 1 {left} {yy} Tm")
            commands.append(f"({escape(line)}) Tj")
        commands.append("ET")
        body = "\n".join(commands).encode("latin-1", "replace")
        content_ids.append(add_obj(f"<< /Length {len(body)} >>\nstream\n".encode("ascii") + body + b"\nendstream"))

    page_ids = [
        add_obj(
            "<< /Type /Page /Parent PARENT /MediaBox "
            f"[0 0 {page_w} {page_h}] /Contents {cid} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R /F2 {font_bold} 0 R >> >> >>"
        )
        for cid in content_ids
    ]
    pages_id = add_obj(
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] >>"
    )
    catalog = add_obj(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    for pid in page_ids:
        objects[pid - 1] = str(objects[pid - 1]).replace("/Parent PARENT", f"/Parent {pages_id} 0 R")

    blob = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(blob))
        header = f"{index} 0 obj\n".encode("ascii")
        if isinstance(obj, bytes):
            blob += header + obj + b"\nendobj\n"
        else:
            blob += header + obj.encode("latin-1") + b"\nendobj\n"
    xref = len(blob)
    blob += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    blob += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        blob += f"{offset:010d} 00000 n \n".encode("ascii")
    blob += (
        f"trailer << /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


if __name__ == "__main__":
    destination = Path(__file__).resolve().parent / "two-minute-script.pdf"
    build(destination)
    print(f"{spoken_words()} spoken words")
    print(destination)
