"""把 allagent.md 转换为自包含单文件网页(零外部依赖,可直接静态托管发布)。"""
from __future__ import annotations

import html as htmlmod
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def inline(text: str) -> str:
    """行内格式:加粗 / 行内代码 / 链接(先转义防注入)。"""
    text = htmlmod.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def slug(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")


def md_to_html(md: str) -> tuple[str, list[tuple[str, str]]]:
    lines = md.splitlines()
    out: list[str] = []
    toc: list[tuple[str, str]] = []
    i = 0
    n = len(lines)

    def close_list() -> None:
        if out and out[-1] in ("<ul>", "<ol>"):
            out.append(f"</{out[-1][1:2]}l>")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 代码围栏
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            block = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            close_list()
            code = htmlmod.escape("\n".join(block))
            cls = f' class="lang-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        # 标题
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            close_list()
            if level == 2:
                sid = slug(text)
                toc.append((text, sid))
                out.append(f'<h2 id="{sid}">{inline(text)}</h2>')
            elif level == 3:
                out.append(f"<h3>{inline(text)}</h3>")
            else:
                out.append(f"<h1>{inline(text)}</h1>")
            i += 1
            continue

        # 表格
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|?$", lines[i + 1].strip()):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            rows = []
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            close_list()
            head = "".join(f"<th>{inline(c)}</th>" for c in header)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                for row in rows)
            out.append(f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
            continue

        # 引用
        if stripped.startswith(">"):
            close_list()
            quotes = [stripped.lstrip("> ")]
            i += 1
            while i < n and lines[i].strip().startswith(">"):
                quotes.append(lines[i].strip().lstrip("> "))
                i += 1
            out.append("<blockquote>" + " ".join(inline(q) for q in quotes) + "</blockquote>")
            continue

        # 分隔线
        if re.match(r"^-{3,}$", stripped):
            close_list()
            out.append("<hr>")
            i += 1
            continue

        # 无序列表
        if re.match(r"^[-*]\s+", stripped):
            close_list()
            out.append("<ul>")
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                item = re.sub(r"^[-*]\s+", "", lines[i].strip())
                # 列表内的嵌套续行:简单并入同一项
                parts = [item]
                i += 1
                while i < n and lines[i].startswith("  ") and lines[i].strip() and not re.match(r"^\s+[-*]\s+", lines[i]):
                    parts.append(lines[i].strip())
                    i += 1
                out.append(f"<li>{inline(' '.join(parts))}</li>")
            out.append("</ul>")
            continue

        # 有序列表
        if re.match(r"^\d+\.\s+", stripped):
            close_list()
            out.append("<ol>")
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                item = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                parts = [item]
                i += 1
                while i < n and lines[i].startswith("  ") and lines[i].strip() and not re.match(r"^\s+\d+\.\s+", lines[i]):
                    parts.append(lines[i].strip())
                    i += 1
                out.append(f"<li>{inline(' '.join(parts))}</li>")
            out.append("</ol>")
            continue

        # 普通段落
        if stripped:
            close_list()
            out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    close_list()
    return "\n".join(out), toc


PAGE_CSS = """
:root { --primary:#1F4E79; --accent:#0EA5E9; --grad:linear-gradient(135deg,#1F4E79 0%,#0E5A8A 55%,#0EA5E9 100%);
  --bg:#F4F8FC; --text:#2B3A4A; --muted:#7A8BA0; --border:#DCE6F0; }
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:"Microsoft YaHei","微软雅黑","PingFang SC",sans-serif; background:
  radial-gradient(1100px 480px at 88% -8%, rgba(14,165,233,.12), transparent 60%),
  radial-gradient(900px 420px at -8% 108%, rgba(31,78,121,.12), transparent 60%), var(--bg);
  color:var(--text); line-height:1.8; }
.hero { background:var(--grad); color:#fff; padding:56px 24px 44px; text-align:center; }
.hero h1 { font-size:32px; letter-spacing:1px; margin-bottom:12px; }
.hero p { opacity:.92; font-size:15px; max-width:760px; margin:0 auto; }
.layout { display:flex; max-width:1180px; margin:0 auto; padding:32px 24px 80px; gap:36px; }
.toc { flex:0 0 220px; position:sticky; top:24px; align-self:flex-start; background:rgba(255,255,255,.85);
  backdrop-filter:blur(8px); border:1px solid var(--border); border-radius:14px; padding:18px;
  box-shadow:0 6px 24px rgba(31,78,121,.10); font-size:13px; max-height:calc(100vh - 48px); overflow:auto; }
.toc a { display:block; color:var(--text); text-decoration:none; padding:6px 10px; border-radius:8px; }
.toc a:hover { background:rgba(14,165,233,.10); color:var(--primary); }
.content { flex:1; min-width:0; }
.content h2 { font-size:24px; margin:44px 0 16px; padding-bottom:10px; border-bottom:2px solid transparent;
  border-image:var(--grad) 1; color:var(--primary); scroll-margin-top:24px; }
.content h3 { font-size:18px; margin:26px 0 10px; color:var(--primary); }
.content p { margin:10px 0; font-size:15px; }
.content strong { color:#16385A; }
.content code { background:rgba(14,165,233,.10); color:#0E5A8A; padding:2px 6px; border-radius:5px;
  font-family:Consolas,"Courier New",monospace; font-size:13px; }
.content pre { background:#0F1B2D; color:#D6E4F5; border-radius:12px; padding:18px 20px; overflow-x:auto;
  margin:14px 0; font-size:13px; line-height:1.7; box-shadow:0 6px 20px rgba(15,27,45,.25); }
.content pre code { background:none; color:inherit; padding:0; font-size:13px; }
.table-wrap { overflow-x:auto; margin:14px 0; border-radius:12px; box-shadow:0 4px 16px rgba(31,78,121,.08); }
table { border-collapse:collapse; width:100%; background:#fff; font-size:14px; }
th { background:var(--grad); color:#fff; padding:10px 14px; text-align:left; white-space:nowrap; }
td { padding:9px 14px; border-bottom:1px solid var(--border); vertical-align:top; }
tr:nth-child(even) td { background:#F7FAFD; }
ul, ol { margin:10px 0 10px 24px; font-size:15px; }
li { margin:6px 0; }
blockquote { border-left:4px solid var(--accent); background:rgba(14,165,233,.06); margin:14px 0;
  padding:12px 18px; border-radius:0 10px 10px 0; color:#3D5568; }
hr { border:none; height:1px; background:var(--border); margin:32px 0; }
a { color:var(--accent); }
@media (max-width:900px) { .layout { flex-direction:column; } .toc { position:static; flex:none; } }
"""


def build_site(md: str) -> str:
    body, toc = md_to_html(md)
    # 标题与首段引用移到 hero 区
    hero_title = re.search(r"<h1>(.*?)</h1>", body).group(1)
    body = re.sub(r"<h1>.*?</h1>\s*", "", body, count=1)
    hero_sub = ""
    m = re.search(r"<blockquote>(.*?)</blockquote>", body)
    if m:
        hero_sub = m.group(1)
        body = body.replace(m.group(0), "", 1)
    toc_html = "".join(f'<a href="#{sid}">{htmlmod.escape(t)}</a>' for t, sid in toc)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>综合性 AI 运营智能体(AllAgent)</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="hero">
  <h1>{hero_title}</h1>
  <p>{hero_sub}</p>
</div>
<div class="layout">
  <nav class="toc"><div style="font-weight:bold;color:var(--primary);margin-bottom:8px;">目录</div>{toc_html}</nav>
  <main class="content">{body}</main>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    src = ROOT / "allagent.md"
    html = build_site(src.read_text(encoding="utf-8"))
    for dst in (ROOT / "allagent.html", ROOT / "static" / "allagent.html"):
        dst.write_text(html, encoding="utf-8")
        print(f"已生成: {dst}  ({len(html.encode('utf-8')) / 1024:.1f} KB)")
