from pathlib import Path

from nokia_docs.parse import parse_html


def test_parse_webhelp_fixture_extracts_nested_sections(tmp_path: Path):
    html_path = tmp_path / "26-3" / "7750-sr" / "books" / "mpls" / "rsvp.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        """<!doctype html>
        <html>
          <head><title>MPLS and RSVP</title></head>
          <body>
            <div class="wh_topic_content">
              <article id="rsvp-root" class="nested0">
                <h1>RSVP configuration</h1>
                <p>Configure RSVP globally.</p>
                <article id="rsvp-interface" class="nested1">
                  <h2>RSVP interface</h2>
                  <p>Enable RSVP on an interface.</p>
                </article>
              </article>
            </div>
          </body>
        </html>""",
        encoding="utf-8",
    )

    chunks = parse_html(html_path, tmp_path)

    assert [c.section_id for c in chunks] == ["rsvp-root", "rsvp-interface"]
    assert chunks[0].product_line == "sros-26-3"
    assert chunks[0].book == "mpls"
    assert chunks[1].section_path == "RSVP configuration > RSVP interface"


def test_parse_nsp_fixture_extracts_core_page(tmp_path: Path):
    html_path = tmp_path / "NSP webdocs" / "Operations_Guide" / "alarm.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        """<!doctype html>
        <html>
          <head><title>Alarm guide</title></head>
          <body id="alarm-page">
            <div id="core">
              <h4 class="pMapTitle">Alarm Management</h4>
              <p>Use this page to review active alarms.</p>
            </div>
          </body>
        </html>""",
        encoding="utf-8",
    )

    chunks = parse_html(html_path, tmp_path)

    assert len(chunks) == 1
    assert chunks[0].product_line == "nsp"
    assert chunks[0].book == "Operations_Guide"
    assert chunks[0].section_title == "Alarm Management"
