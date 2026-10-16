#!/usr/bin/env ruby
# frozen_string_literal: true

# scripts/site_checks/proof.rb
#
# PROOF layer: html-proofer on the built _site, offline, with findings
# forwarded through the severity model (ERROR/WARN/WAIVED) instead of a
# hard abort — so the user can override knowing what will/won't break.
#
# html-proofer resolves internal hrefs relative to the docroot; the site
# builds with baseurl /courses (or /courses-preview), so swap the prefix
# away (Regexp keys required in proofer v5) and check _site directly.
#
# Classification (maps output failures back to SOURCE files when possible):
#   ERROR  — internal link → missing page (404); internal image missing;
#            empty src attribute
#   WARN   — mixed-relative image path (../assets/img/... works on GitHub
#            Pages but breaks extensionless local servers); backslash
#            paths (assets\img\... break on Linux-deployed Pages); comma-
#            joined srcs (parallaxBackgroundImage lists resolve as one URL)
#
# A Unicode NFD filename (e.g. wg-glühwein.jpg composed as "u" + U+0308)
# appears as %CC%88 in the URL: the file exists on macOS but Linux-backed
# GitHub Pages serves NFC paths → the deployed site 404s it. Reported as
# ERROR with a fix note.
#
# Usage:
#   ruby scripts/site_checks/proof.rb --json out.json
#   ruby scripts/site_checks/proof.rb --site _site --root /path/to/repo

require_relative 'test_report'

require 'cgi'
require 'uri'

module SiteChecks
  module Proof
    module_function

    def run(root:, site_dir:, rep:, gemfile_env: true)
      require 'html-proofer'
      baseurl = baseurl_from_config(root)
      options = {
        disable_external: true,
        allow_hash_href: true,
        check_favicon: false,
        enforce_https: false,    # content may link http; offline mode can't check externals anyway
        ignore_files: [%r{assets/reveal\.js/}] # vendored submodule: demo/test files reference node_modules
      }
      options[:swap_urls] = { %r{\A#{Regexp.escape(baseurl)}} => '' } if baseurl && baseurl != '/'

      failed = false
      failures = []
      require 'html-proofer'
      runner = HTMLProofer.check_directory(site_dir, options)
      begin
        runner.run
        # Proofer v5 EXITS (SystemExit) on failures instead of raising —
        # catch it and read the failure list off the runner.
      rescue SystemExit
        failed = true
      end
      failures = runner.instance_variable_get(:@failures) || []
      classify(failures, root, rep)
      failed
    end

    def classify(failures, root, rep)
      errs = 0
      warns = 0
      failures.each do |f|
        out_file = f.path.to_s
        line = f.line
        msg = f.description.to_s

        # Map the OUTPUT html back to the SOURCE file (site 26rw/1.html → _course_26rw/2026-*-1.md).
        src = source_for_output(out_file, root)

        # Report paths RELATIVE to the repo root so waivers (regexes in
        # config/test_waivers.yml) match identically on macOS and in CI
        # (where the repo lives at /home/runner/work/courses/courses).
        rel = ->(p) { p && p.start_with?(root) ? p.delete_prefix("#{root}/") : p }

        kind = classify_kind(msg)
        next if kind == :skip

        if kind == :error
          errs += 1
          rep.emit severity: 'ERROR', check_id: 'proof',
                   file: rel.call(src || out_file), line: line,
                   message: "#{msg} (output: #{rel.call(out_file)})",
                   fix: fix_for(msg),
                   sanitizer: 'rewrite the link/src to the correct path'
        else
          warns += 1
          rep.emit severity: 'WARN', check_id: 'proof',
                   file: rel.call(src || out_file), line: line,
                   message: "#{msg} (output: #{rel.call(out_file)})",
                   fix: fix_for(msg)
        end
      end
      rep.ok('proof', "html-proofer: #{failures.size} raw finding(s) → #{errs} ERROR, #{warns} WARN") if failures.any?
      rep.ok('proof', 'html-proofer: internal links, images, and scripts all resolve') if failures.empty?
    end

    def classify_kind(msg)
      case msg
      when /is not an HTTPS link/ then :skip      # external links unchecked offline
      when %r{image /courses/assets/img/ does not exist|internal image /courses/assets/img/ does not exist} then :error # empty src
      when /does not have an alt attribute/ then :skip # accessibility, not display breakage
      when /has no src or srcset/ then :error
      when /internally linking to .* does not exist/ then :error
      when /internal image .* does not exist/
        return :warn if msg.include?('..') || msg.include?('\\') || msg.include?(',') || msg.include?('%CC%88') || msg.include?('%cc%88')
        :error
      when /internal script reference .* does not exist/ then :error
      when /the hash .* does not/ then :skip      # fragment anchors (reveal.js navigation)
      else :error
      end
    end

    def fix_for(msg)
      if msg.include?('%CC')
        'NFD filename (decomposed umlaut): rename the file NFC on disk (iconv -f utf-8-mac -t utf-8) and re-commit'
      elsif msg.include?('\\')
        'backslash path: use forward slashes (assets/img/...) — backslashes break on Linux-deployed Pages'
      elsif msg.include?(',') && msg.include?('does not exist')
        'comma-joined src list resolves as ONE url — split into separate attributes or use one image'
      elsif msg =~ %r{\.\./}
        'mixed-relative path works on GitHub Pages but breaks extensionless local servers — use {{ site.baseurl }}/assets/img/...'
      elsif msg.include?('internally linking to')
        'fix or remove the internal link (target page missing from the build)'
      elsif msg.include?('has no src or srcset')
        'remove the empty <img> or set src'
      elsif msg =~ %r{assets/img/ does not exist}
        'empty src attribute (image front matter unset?) — set the image or remove the <img>'
      elsif msg.include?('internal image')
        'broken relative src: a plain assets/img/... src under /courses/<course>/ 404s — use ../assets/img/... or {{ site.baseurl }}/assets/img/...'
      elsif msg.include?('internal script reference')
        'fix the script path (missing from assets/)'
      else
        'inspect the referenced path'
      end
    end

    # _site/26rw/1.html → the session doc source (2026-10-12-1.md) when resolvable.
    def source_for_output(out_path, root)
      m = out_path.match(%r{_site/(?<slug>[^/]+)/(?<name>.+)\.html\z})
      return nil unless m
      course_dir = File.join(root, "_course_#{m[:slug]}")
      return nil unless Dir.exist?(course_dir)
      name = m[:name]
      if name.match?(/\A\d+-slides\z/)
        # Deck: _site/26rw/10-slides.html → 2026-12-14-10-slides.md
        Dir.glob(File.join(course_dir, "*-#{name}.md")).sort.first
      elsif name.match?(/\A\d+\z/)
        # Session doc: _site/26rw/1.html → 2026-10-12-1.md (the -slides deck
        # ends -1-slides.md, so it never matches *-1.md)
        Dir.glob(File.join(course_dir, "*-#{name}.md")).sort.first
      else
        File.join(course_dir, "#{name}.md")
      end
    rescue StandardError
      nil
    end

    def baseurl_from_config(root)
      require 'yaml'
      config_path = File.join(root, '_config.yml')
      return '/' unless File.file?(config_path)
      config = YAML.safe_load(File.read(config_path), permitted_classes: [Date, Time]) || {}
      b = config['baseurl'].to_s
      b.empty? ? '/' : (b.start_with?('/') ? b : "/#{b}")
    rescue StandardError
      '/'
    end
  end
end

# ---------- CLI ----------
if __FILE__ == $PROGRAM_NAME
  args = ARGV.dup
  root = File.expand_path('../..', __dir__)
  site_dir = File.join(root, '_site')
  json_out = nil
  until args.empty?
    case args.shift
    when '--root' then root = File.expand_path(args.shift)
    when '--site' then site_dir = File.expand_path(args.shift, Dir.pwd)
    when '--json' then json_out = args.shift
    end
  end

  waivers = File.join(root, 'config', 'test_waivers.yml')
  rep = SiteChecks::Reporter.new(waivers_path: waivers)
  failed = SiteChecks::Proof.run(root: root, site_dir: site_dir, rep: rep)
  rep.write_json(json_out) if json_out
  puts '── proof summary: ' + rep.summary_line + ' ──'
  exit rep.exit_code
end
