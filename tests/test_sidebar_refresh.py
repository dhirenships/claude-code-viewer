import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class SidebarRefreshTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "Node.js is required for the browser logic test"
    )
    def test_latest_sidebar_refresh_wins_when_responses_finish_out_of_order(self):
        app_js = Path(__file__).parents[1] / "cocomon" / "static" / "js" / "app.js"
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            global.window = {{
                location: new URL('http://viewer.test/?q=WeeklyUpdate'),
                formatFileSize: null,
                formatRelativeTime: null,
            }};
            global.document = {{ addEventListener() {{}} }};

            const source = fs.readFileSync({str(app_js)!r}, 'utf8');
            vm.runInThisContext(source + '\\nglobalThis.TestClaudeViewer = ClaudeViewer;');

            let liveSidebar = {{
                kind: 'initial',
                classList: {{ contains() {{ return false; }} }},
                replaceWith(next) {{
                    if (liveSidebar === this) liveSidebar = next;
                }},
            }};
            global.document.querySelector = selector => (
                selector === '.session-sidebar' ? liveSidebar : null
            );
            global.DOMParser = class {{
                parseFromString(html) {{
                    return {{
                        querySelector() {{
                            return {{
                                kind: html,
                                classList: {{ add() {{}}, contains() {{ return false; }} }},
                                replaceWith(next) {{
                                    if (liveSidebar === this) liveSidebar = next;
                                }},
                            }};
                        }},
                    }};
                }}
            }};

            const pending = [];
            global.fetch = url => new Promise(resolve => pending.push({{ url, resolve }}));

            const viewer = Object.create(TestClaudeViewer.prototype);
            viewer.sidebarRefreshSequence = 0;
            viewer.bindSidebarControls = () => {{}};
            viewer.setupSidebar = () => {{}};
            viewer.rebindMobileSidebar = () => {{}};

            window.location = new URL('http://viewer.test/');
            const staleRefresh = viewer.refreshSidebarHtml();
            window.location = new URL('http://viewer.test/?q=WeeklyUpdate');
            const currentRefresh = viewer.refreshSidebarHtml();

            const response = html => ({{ ok: true, text: async () => html }});
            pending[0].resolve(response('unfiltered'));
            setImmediate(() => pending[1].resolve(response('filtered')));

            Promise.all([staleRefresh, currentRefresh]).then(() => {{
                if (liveSidebar.kind !== 'filtered') {{
                    console.error(`Expected filtered sidebar, got ${{liveSidebar.kind}}`);
                    process.exit(1);
                }}
            }}).catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
