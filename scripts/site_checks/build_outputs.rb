#!/usr/bin/env ruby
# frozen_string_literal: true

# scripts/site_checks/build_outputs.rb
#
# BUILD layer census: runs AFTER `jekyll build` and X-rays what Jekyll
# actually emitted, catching the silent failures where the build "succeeds"
# but the output is wrong:
#
#   unregistered-collection-emitted   registered collection emitted nothing
#                                     into _site/<slug>/ (silent 404s)
#   slides-rendered                   a -slides.md produced no HTML, or its
#                                     HTML has no <div class="reveal"> / no
#                                     <section> (revealify didn't run — e.g.
#                                     a plain GitHub Pages --safe build)
#   session-title-composed            a session doc's emitted page <title>
#                                     does not contain the composed
#                                     "N. Unit: Long-topic" (session-meta
#                                     machinery broken)
#   lfs-pointers                      files in _site that are unsmudged LFS
#                                     pointers (deployed site shows broken
#                                     images)
#   build-crash                       jekyll build itself failed; translate
#                                     the trace into file:line where possible
#
# Usage:
#   ruby scripts/site_checks/build_outputs.rb --site _site --log build.log
#   ruby scripts/site_checks/build_outputs.rb --json out.json

require_relative 'test_report'

require 'yaml'

module SiteChecks
  module BuildOutputs
    module_function

    LFS_HEADER = 'version https://git-lfs.github.com/spec'

    def check(root:, site_dir:, build_log:, rep:)
      errs = 0
      errs += check_collections_emitted(root, site_dir, rep)
      errs += check_slides_rendered(root, site_dir, rep)
      errs += check_session_titles(root, site_dir, rep)
      errs += check_lfs_site(site_dir, rep)
      check_build_crash(build_log, rep) # emits findings; failures counted via reporter
      errs
    end

    # ---------- checks ----------

    def registered_collections(root)
      config_path = File.join(root, '_config.yml')
      return {} unless File.file?(config_path)
      config = YAML.safe_load(File.read(config_path), permitted_classes: [Date, Time]) || {}
      collections = config['collections'] || {}
      out = {}
      collections.each do |key, val|
        out[key] = { slug: key.sub(/\Acourse_/, ''),
                     output: val.is_a?(Hash) ? val['output'] : false }
      end
      out
    rescue Psych::SyntaxError
      {}
    end

    def check_collections_emitted(root, site_dir, rep)
      errs = 0
      registered = registered_collections(root)
      registered.each do |key, rule|
        next unless rule[:output]
        slug = rule[:slug]
        emitted = Dir.glob(File.join(site_dir, slug, '**', '*.html'))
        next unless emitted.empty?
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'collection-emitted',
                 file: "_#{key}", line: nil,
                 message: "registered collection '#{key}' emitted NOTHING into _site/#{slug}/ — " \
                          "every page 404s on the served site",
                 fix: 'check the collection permalink in _config.yml and that files have front matter',
                 sanitizer: nil
      end
      rep.ok('collection-emitted', "#{registered.size} registered collection(s), all emitted HTML") if errs.zero?
      errs
    end

    def check_slides_rendered(root, site_dir, rep)
      errs = 0
      decks = 0
      Dir.glob(File.join(root, '_course_*', '*-slides.md')).sort.each do |src|
        m = File.basename(src).match(/\A\d{4}-\d{2}-\d{2}-(.+?)\.md\z/)
        slug = m && m[1] # :title slug keeps "-slides": 2026-10-12-1-slides.md → "1-slides"
        next unless slug
        course_dir = File.basename(File.dirname(src)) # _course_<slug>
        course_slug = course_dir.sub(/\A_course_/, '')
        html_path = File.join(site_dir, course_slug, "#{slug}.html")
        decks += 1
        unless File.file?(html_path)
          errs += 1
          rep.emit severity: 'ERROR', check_id: 'slides-rendered',
                   file: src, line: nil,
                   message: "slide deck produced NO HTML (expected _site/#{course_slug}/#{slug}.html) — " \
                            "the deck 404s or renders blank",
                   fix: 'check the deck built (front matter, collection registered) and that jekyll ran with plugins (not --safe)',
                   sanitizer: nil
          next
        end
        html = File.read(html_path, mode: 'r:UTF-8')
        has_reveal = html.include?('class="reveal"')
        has_section = html.include?('<section')
        next if has_reveal && has_section
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'slides-rendered',
                 file: src, line: nil,
                 message: "slide deck HTML is missing #{has_reveal ? 'slide <section>s' : %q(<div class="reveal">)} " \
                          "(#{html_path}) — revealify did not run (plain --safe build?) or the deck is malformed",
                 fix: 'build through the Actions workflow (plugins enabled), not a plain GitHub Pages --safe build',
                 sanitizer: nil
      end
      rep.ok('slides-rendered', "#{decks} slide deck(s), all rendered with reveal <section>s") if errs.zero?
      errs
    end

    def check_session_titles(root, site_dir, rep)
      errs = 0
      docs = 0
      Dir.glob(File.join(root, '_course_*', '*.md')).sort.each do |src|
        name = File.basename(src)
        m = name.match(/\A\d{4}-\d{2}-\d{2}-(\d+)\.md\z/)
        next unless m # session docs only (not -slides.md)
        fm_text = File.read(src, mode: 'r:UTF-8')[/\A---\r?\n(.*?)^---\s*$/m, 1]
        next if fm_text.nil?
        fm = YAML.safe_load(fm_text, permitted_classes: [Date, Time]) rescue nil
        next unless fm.is_a?(Hash)
        session = fm['session']
        unit = fm['unit']
        long_topic = fm['long-topic']
        next if session.nil? || unit.nil? || long_topic.nil?
        docs += 1
        composed = "#{session}. #{unit}: #{long_topic}"
        course_slug = File.basename(File.dirname(src)).sub(/\A_course_/, '')
        html_path = File.join(site_dir, course_slug, "#{m[1]}.html")
        unless File.file?(html_path)
          errs += 1
          rep.emit severity: 'ERROR', check_id: 'session-title-composed',
                   file: src, line: nil,
                   message: "session doc produced NO HTML (expected _site/#{course_slug}/#{m[1]}.html)",
                   fix: 'check the collection is registered and the file has valid front matter',
                   sanitizer: nil
          next
        end
        title = File.read(html_path, mode: 'r:UTF-8')[/<title[^>]*>(.*?)<\/title>/m, 1].to_s
        next if title.include?(session.to_s) && title.include?(long_topic.to_s)
        errs += 1
        rep.emit severity: 'WARN', check_id: 'session-title-composed',
                 file: src, line: nil,
                 message: "emitted <title> is #{title.inspect}; expected the composed '#{composed}' " \
                          "(session-meta.html machinery may be bypassed)",
                 fix: 'check _includes/session-meta.html composition and the post layout',
                 sanitizer: nil
      end
      rep.ok('session-title-composed', "#{docs} session doc(s), titles composed via session-meta") if errs.zero?
      errs
    end

    def check_lfs_site(site_dir, rep)
      errs = 0
      suspicious = Dir.glob(File.join(site_dir, '**', '*')).select do |p|
        File.file?(p) && File.size(p) < 400 && %w[.png .jpg .jpeg .gif .webp .svg .ico .woff .woff2 .ttf .mp3 .mp4 .xlsx .zip].include?(File.extname(p))
      end
      suspicious.each do |path|
        head = File.open(path, 'rb') { |f| f.read(64) }.to_s
        next unless head.include?('git-lfs.github.com/spec')
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'lfs-pointers',
                 file: path, line: nil,
                 message: 'unsmudged Git LFS pointer in the BUILD OUTPUT — the deployed site would show a broken/missing image',
                 fix: 'build with `lfs: true` checkout (actions/checkout) or run git lfs pull before building',
                 sanitizer: nil
      end
      rep.ok('lfs-pointers', "no unsmudged LFS pointers in _site (checked #{suspicious.size} small binaries)") if errs.zero?
      errs
    end

    def check_build_crash(build_log, rep)
      return if build_log.nil? || !File.file?(build_log)
      log = File.read(build_log, mode: 'r:UTF-8')
      # Jekyll failure footer: "jekyll 3.x | Error:  <message>"
      if (m = log.match(/^\s*jekyll [\d.]+\s*\|\s*Error:\s*(.+)$/))
        msg = m[1].strip
        file = nil
        line = nil
        # yaml error: "(<file>): <problem> at line <n> column <m>"
        if (fm = msg.match(/\(([^)]+\.(?:yml|yaml|md|html))\):\s*(.*?)(?:\s+at line (\d+))?/i))
          file = fm[1]
          line = fm[3]&.to_i
          msg = fm[2]
        elsif (lf = msg.match(/(?:in\s+)?(?:file\s+)?([^\s:]+\.(?:md|html|yml|yaml))/i))
          file = lf[1]
        end
        rep.emit severity: 'ERROR', check_id: 'build-crash',
                 file: file, line: line,
                 message: "jekyll build FAILED: #{msg}",
                 fix: 'see the build log; lint checks above usually name the exact source file',
                 sanitizer: nil
      end
    end
  end
end

# ---------- CLI ----------
if __FILE__ == $PROGRAM_NAME
  args = ARGV.dup
  root = File.expand_path('../..', __dir__)
  site_dir = File.join(root, '_site')
  build_log = nil
  json_out = nil
  until args.empty?
    case args.shift
    when '--site' then site_dir = File.expand_path(args.shift, Dir.pwd)
    when '--log' then build_log = File.expand_path(args.shift, Dir.pwd)
    when '--json' then json_out = args.shift
    end
  end

  waivers = File.join(root, 'config', 'test_waivers.yml')
  rep = SiteChecks::Reporter.new(waivers_path: waivers)
  SiteChecks::BuildOutputs.check(root: root, site_dir: site_dir, build_log: build_log, rep: rep)
  rep.write_json(json_out) if json_out
  puts "── build-outputs summary: #{rep.summary_line} ──"
  exit rep.exit_code
end
