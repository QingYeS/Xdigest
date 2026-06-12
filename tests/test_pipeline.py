"""xhs_pipeline 集成测试：mock 模式端到端跑通，产出 HTML + PNG。"""
from __future__ import annotations


def test_generate_xhs_mock_produces_html_and_pngs(tmp_path, monkeypatch):
    """mock=True 时应生成 preview.html 和至少 3 张 PNG（封面+卡片+尾页）。"""
    monkeypatch.setenv("XHS_OUTPUT_DIR", str(tmp_path))
    from xhs_pipeline import generate_xhs
    out_dir = generate_xhs([], "盘前", mock=True)
    assert (out_dir / "preview.html").exists(), "preview.html 未生成"
    pngs = list(out_dir.glob("*.png"))
    assert len(pngs) >= 3, f"PNG 文件不足 3 张，实际: {[p.name for p in pngs]}"


def test_generate_xhs_mock_html_contains_disclaimer(tmp_path, monkeypatch):
    """生成的 preview.html 应包含免责声明文本。"""
    monkeypatch.setenv("XHS_OUTPUT_DIR", str(tmp_path))
    from xhs_pipeline import generate_xhs
    out_dir = generate_xhs([], "盘后", mock=True)
    html = (out_dir / "preview.html").read_text(encoding="utf-8")
    assert "不构成任何投资建议" in html


def test_generate_xhs_mock_returns_path(tmp_path, monkeypatch):
    """generate_xhs 返回的路径应存在且包含输出文件。"""
    monkeypatch.setenv("XHS_OUTPUT_DIR", str(tmp_path))
    from xhs_pipeline import generate_xhs
    out_dir = generate_xhs([], "盘前", mock=True)
    assert out_dir.exists()
    assert any(out_dir.iterdir())
