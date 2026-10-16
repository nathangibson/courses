#!/usr/bin/env ruby
# frozen_string_literal: true

# scripts/site_checks/lint.rb
#
# LINT layer of the site test suite: fast source-level checks that run
# BEFORE jekyll (seconds) and report precise file+line for problems that
# Jekyll either reports opaquely or silently ignores.
#
# Checks:
#   yaml-control-chars      (delegated to scripts/check_yaml_control_chars.rb)
#   front-matter            YAML front matter parses (Psych safe_load with
#                           Date/Time permitted, mirroring Jekyll); names the
#                           real file+line where Jekyll's Psych::SyntaxError
#                           may cite the wrong place
#   unregistered-collection _course_<slug>/ dir with no _config.yml entry
#                           builds nothing and 404s silently (jekyll#6656)
#   permalink-conflicts     two files claiming the same destination URL →
#                           Jekyll's "Conflict: destination is shared by
#                           multiple files" names NO source files (jekyll#8522);
#                           this check names ALL of them
#   session-docs            session docs missing session/unit/long-topic
#                           (title silently falls back to the filename slug);
#                           slide decks (-slides.md) without a matching
#                           session doc
#   lfs-pointers            committed image files that are unsmudged Git LFS
#                           pointers (tiny text) in the repo
#
# Usage:
#   ruby scripts/site_checks/lint.rb                # full lint, exit 1 on ERROR
#   ruby scripts/site_checks/lint.rb --json out.json
#   ruby scripts/site_checks/lint.rb --root /other/repo

require_relative 'test_report'

require 'yaml'
require 'set'

module SiteChecks
  module Lint
    module_function

    IMAGE_EXT = %w[.png .jpg .jpeg .gif .webp .svg .ico .mp3 .wav .ogg .woff .woff2 .ttf .eot .mov .mp4 .xlsx .zip].freeze

    # ---------- helpers ----------

    def content_files(root)
      Dir.glob(File.join(root, '_course_*', '**', '*.{md,markdown}')).sort +
        Dir.glob(File.join(root, '*.md')).sort
    end

    def split_front_matter(path)
      text = File.read(path, mode: 'r:UTF-8')
      return [nil, text] unless text.start_with?("---\n", "---\r\n")
      rest = text.sub(/\A---\r?\n/, '')
      m = rest.match(/\A(?<fm>.*?)^---\s*$/m)
      return [nil, text] unless m
      [m[:fm], m.post_match.to_s]
    end

    def load_fm(fm_text)
      YAML.safe_load(fm_text, permitted_classes: [Date, Time])
    rescue StandardError
      nil
    end

    def registered_collections(root)
      config_path = File.join(root, '_config.yml')
      return {} unless File.file?(config_path)
      config = YAML.safe_load(File.read(config_path), permitted_classes: [Date, Time]) || {}
      collections = config['collections'] || {}
      out = {}
      collections.each do |key, val|
        slug = key.sub(/\Acourse_/, '')
        out[key] = { slug: slug, output: val.is_a?(Hash) ? val['output'] : false,
                     permalink: val.is_a?(Hash) ? val['permalink'] : nil }
      end
      out
    rescue Psych::SyntaxError => e
      { __error__: e }
    end

    # Effective site URL a file will claim (for conflict detection).
    # Order mirrors Jekyll: front-matter permalink OVERRIDES collection rule.
    def effective_dest(path, fm, collection_rule)
      return nil if fm.nil?
      permalink = fm.is_a?(Hash) ? fm['permalink'] : nil
      if permalink.is_a?(String) && !permalink.empty?
        return normalize_dest(permalink)
      end
      return nil unless collection_rule && collection_rule[:output]

      slug = collection_rule[:slug]
      name = File.basename(path)
      if (m = name.match(/\A\d{4}-\d{2}-\d{2}-(.+?)\.md\z/))
        # :title slug strips the leading ISO date and extension only —
        # Jekyll does NOT strip "-slides", so 2026-10-12-1-slides.md → "1-slides"
        normalize_dest("/#{slug}/#{m[1]}")
      elsif name == 'index.md'
        normalize_dest("/#{slug}/")
      else
        normalize_dest("/#{slug}/#{name.sub(/\.md\z/, '')}")
      end
    end

    def normalize_dest(dest)
      d = dest.to_s.chomp('/')
      d = "/#{d}" unless d.start_with?('/')
      d.empty? ? '/' : d
    end

    # ---------- checks (each returns its own error count) ----------

    def check_front_matter(root, rep)
      errs = 0
      files = content_files(root)
      files.each do |path|
        fm_text, = split_front_matter(path)
        next if fm_text.nil? # no front matter — plain md, fine
        begin
          YAML.safe_load(fm_text, permitted_classes: [Date, Time])
        rescue Psych::SyntaxError => e
          errs += 1
          line = e.line ? e.line + 1 : nil
          rep.emit severity: 'ERROR', check_id: 'front-matter',
                   file: path, line: line,
                   message: "front matter YAML does not parse: #{e.message.strip}",
                   fix: 'fix the YAML syntax (indentation, quotes, tabs) in the front-matter block',
                   sanitizer: 'yaml front-matter formatter'
        rescue StandardError => e
          errs += 1
          rep.emit severity: 'ERROR', check_id: 'front-matter',
                   file: path, line: nil,
                   message: "front matter unreadable: #{e.message}",
                   fix: 'inspect the front-matter block',
                   sanitizer: nil
        end
      end
      rep.ok('front-matter', "all content front matter parses (#{files.size} files)") if errs.zero?
      errs
    end

    def check_collections(root, rep)
      registered = registered_collections(root)
      if registered[:__error__]
        rep.emit severity: 'ERROR', check_id: 'unregistered-collection',
                 file: '_config.yml', line: nil,
                 message: "_config.yml collections do not parse: #{registered[:__error__].message}",
                 fix: 'fix the collections block in _config.yml',
                 sanitizer: nil
        return 1
      end
      on_disk = Dir.glob(File.join(root, '_course_*')).select { |p| File.directory?(p) }
      errs = 0
      on_disk.each do |dir|
        dir_name = File.basename(dir)
        # Config keys are course_<slug>; dirs are _course_<slug> → strip the leading underscore.
        matching_key = registered.keys.find { |k| k.to_s == dir_name.sub(/\A_/, '') }
        next if matching_key
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'unregistered-collection',
                 file: dir, line: nil,
                 message: "course directory exists but has NO entry in _config.yml collections — " \
                          "Jekyll builds nothing from it and every page 404s silently (jekyll#6656)",
                 fix: "add to _config.yml:  #{dir_name.sub(/\A_/, '')}: { output: true, permalink: /#{dir_name.sub(/\A_course_/, '')}/:title }",
                 sanitizer: 'append the collection block to _config.yml'
      end
      rep.ok('unregistered-collection', "#{on_disk.size} course dir(s) on disk, all registered") if errs.zero?
      errs
    end

    def check_permalink_conflicts(root, rep)
      registered = registered_collections(root)
      return 1 if registered[:__error__]
      dests = Hash.new { |h, k| h[k] = [] }

      # Static pages in the repo root (Jekyll builds root *.md).
      Dir.glob(File.join(root, '*.md')).sort.each do |path|
        fm_text, = split_front_matter(path)
        next if fm_text.nil?
        fm = load_fm(fm_text)
        dest = effective_dest(path, fm, nil)
        dests[dest] << path if dest
      end

      # Collection files.
      registered.each_key do |key|
        next unless key.to_s.start_with?('course_')
        dir = File.join(root, "_#{key}")
        next unless Dir.exist?(dir)
        rule = registered[key]
        Dir.glob(File.join(dir, '**', '*.md')).sort.each do |path|
          fm_text, = split_front_matter(path)
          fm = fm_text ? load_fm(fm_text) : nil
          dest = effective_dest(path, fm, rule)
          dests[dest] << path if dest
        end
      end

      errs = 0
      dests.each do |dest, paths|
        next unless paths.size > 1
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'permalink-conflicts',
                 file: paths.first, line: nil,
                 message: "#{paths.size} files claim the SAME destination #{dest} — Jekyll's " \
                          "'Conflict: destination is shared by multiple files' names no sources; all of them: " \
                          "#{paths.join(', ')}",
                 fix: 'give each file a distinct permalink (copy-pasted course pages usually keep the old course slug)',
                 sanitizer: 'rewrite permalink: lines to the correct course slug'
      end
      rep.ok('permalink-conflicts', 'no two files claim the same destination URL') if errs.zero?
      errs
    end

    def check_session_docs(root, rep)
      registered = registered_collections(root)
      return 1 if registered[:__error__]
      warns = 0
      paired = 0
      registered.each_key do |key|
        next unless key.to_s.start_with?('course_')
        dir = File.join(root, "_#{key}")
        next unless Dir.exist?(dir)
        sessions = Hash.new { |h, k| h[k] = { doc: nil, slides: [] } }
        Dir.glob(File.join(dir, '*.md')).sort.each do |path|
          name = File.basename(path)
          m = name.match(/\A\d{4}-\d{2}-\d{2}-(\d+)(-slides)?\.md\z/)
          next unless m
          n = m[1]
          if m[2] # slides deck
            sessions[n][:slides] << path
          else
            sessions[n][:doc] = path
            fm_text, = split_front_matter(path)
            fm = fm_text ? load_fm(fm_text) : nil
            next unless fm.is_a?(Hash)
            missing = %w[session unit long-topic].select { |k| fm[k].nil? || fm[k].to_s.strip.empty? }
            next if missing.empty?
            warns += 1
            rep.emit severity: 'WARN', check_id: 'session-docs',
                     file: path, line: nil,
                     message: "session doc missing #{missing.join(', ')} — the composed title " \
                              "'N. Unit: Long-topic' silently falls back to the filename slug (session-meta.html)",
                     fix: "add #{missing.join(' / ')} to the front matter"
          end
        end
        # Orphan slide decks: slides without a session doc.
        sessions.each do |n, s|
          next unless s[:slides].any? && s[:doc].nil?
          s[:slides].each do |slides_path|
            warns += 1
            rep.emit severity: 'WARN', check_id: 'session-docs',
                     file: slides_path, line: nil,
                     message: "slide deck for session #{n} has no matching session doc (#{File.basename(slides_path).sub(/-slides\.md\z/, '.md')})",
                     fix: 'add the session doc or verify this is intentional'
          end
        end
        paired += sessions.count { |_n, s| s[:doc] && s[:slides].any? }
      end
      rep.ok('session-docs', "session docs carry session/unit/long-topic; #{paired} doc+deck pair(s)") if warns.zero?
      0 # warnings never block
    end

    def check_lfs_pointers(root, rep)
      candidates = IMAGE_EXT.flat_map { |ext| Dir.glob(File.join(root, 'assets', '**', "*#{ext}")) }
                            .select { |p| File.file?(p) }
      errs = 0
      candidates.each do |path|
        size = File.size(path)
        next unless size < 400
        head = File.open(path, 'rb') { |f| f.read(64) }.to_s
        next unless head.include?('git-lfs.github.com/spec')
        errs += 1
        rep.emit severity: 'ERROR', check_id: 'lfs-pointers',
                 file: path, line: nil,
                 message: "unsmudged Git LFS pointer (#{size} B of text where a real file should be) — " \
                          "the deployed site would 404 this asset; run `git lfs pull`",
                 fix: 'git lfs install && git lfs pull',
                 sanitizer: nil
      end
      rep.ok('lfs-pointers', "no unsmudged LFS pointers among #{candidates.size} binary assets") if errs.zero?
      errs
    end
  end
end

# ---------- CLI ----------
if __FILE__ == $PROGRAM_NAME
  args = ARGV.dup
  root = File.expand_path('../..', __dir__)
  json_out = nil
  until args.empty?
    case args.shift
    when '--root' then root = File.expand_path(args.shift)
    when '--json' then json_out = args.shift
    end
  end

  waivers = File.join(root, 'config', 'test_waivers.yml')
  rep = SiteChecks::Reporter.new(waivers_path: waivers)

  # Delegate the control-char check to its script (module reuse).
  require_relative '../check_yaml_control_chars'
  SiteChecks::YamlControlChars.run(rep, root)

  SiteChecks::Lint.check_front_matter(root, rep)
  SiteChecks::Lint.check_collections(root, rep)
  SiteChecks::Lint.check_permalink_conflicts(root, rep)
  SiteChecks::Lint.check_session_docs(root, rep)
  SiteChecks::Lint.check_lfs_pointers(root, rep)

  rep.write_json(json_out) if json_out
  puts "── lint summary: #{rep.summary_line} ──"
  exit rep.exit_code
end
