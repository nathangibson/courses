#!/usr/bin/env python3
"""Static server with clean-URL support for the courses Jekyll site.

Serves the _site directory so that /courses/25rw/3 resolves to
/courses/25rw/3.html when no extension is given (mirrors GitHub Pages clean-URL
behavior, which the plain http.server lacks).

Usage: python3 clean_url_server.py <docroot> [port]
"""
import http.server
import functools
import os
import sys

class CleanURLHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Let the base class resolve the literal file path first.
        p = super().translate_path(path)
        # If the path has no extension and a sibling .html exists, serve that.
        if os.path.isdir(p):
            # Directory: try index.html in it
            idx = os.path.join(p, 'index.html')
            if os.path.isfile(idx):
                return idx
        elif not os.path.splitext(p)[1]:
            html = p + '.html'
            if os.path.isfile(html):
                return html
        return p

def main():
    docroot = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    os.chdir(docroot)
    handler = functools.partial(CleanURLHandler, directory=docroot)
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    print(f'Serving {docroot} with clean-URL support on http://127.0.0.1:{port}/')
    httpd.serve_forever()

if __name__ == '__main__':
    main()
