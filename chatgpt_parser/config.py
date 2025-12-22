import re

URL_REGEX = re.compile(r'https?://\S+')
CURRENT_SCHEMA_VERSION = 3
DEFAULT_CSS = """
:root {
  font-family: "Inter", "Helvetica Neue", Arial, sans-serif;
  color: #0f172a;
  background: #f8fafc;
}
body {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px 18px 48px;
  line-height: 1.6;
}
h1, h2, h3, h4 {
  color: #0f172a;
  margin: 1.25em 0 0.35em;
  line-height: 1.25;
}
a { color: #2563eb; }
code {
  font-family: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  background: #eef2ff;
  padding: 0 4px;
  border-radius: 4px;
}
blockquote {
  background: #eef2ff;
  border-left: 4px solid #6366f1;
  padding: 0.85rem 1.1rem;
  margin: 0.35rem 0 1.25rem;
}
hr {
  border: 0;
  border-top: 1px solid #e2e8f0;
  margin: 1.5rem 0;
}
ul {
  padding-left: 1.15rem;
}
.toc {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 1px 2px rgba(15,23,42,0.04);
}
"""
