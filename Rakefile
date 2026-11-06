# frozen_string_literal: true

# Rakefile — site test suite entry points.
#
#   rake lint    # fast source checks (seconds): YAML control chars, front matter,
#                # unregistered collections, permalink conflicts, session docs, LFS
#   rake build   # jekyll build + post-build census (collections emitted, decks
#                # rendered, session titles composed, LFS smudge, crash translation)
#   rake proof   # html-proofer on _site, offline (internal links, images, alt)
#   rake ci      # lint + build + proof — the CI gate
#   rake serve   # lint + build, then jekyll serve (local preview)
#
# Every check reports precise file+line. Severity: ERROR blocks, WARN passes
# with fix guidance, WAIVED = explicitly suppressed in config/test_waivers.yml.

require 'time'

task default: :ci

desc 'Fast source-level checks (seconds)'
task :lint do
  sh 'ruby scripts/site_checks/lint.rb --json tmp/test-lint.json'
end

desc 'Jekyll build + post-build output census'
task :build do
  # PROOF runs against _site afterwards; keep baseurl from _config.yml.
  env = { 'JEKYLL_ENV' => 'production' }
  ok = system(env, 'bundle exec jekyll build --strict-front-matter --trace', out: File::NULL, err: 'tmp/build.log')
  if ok
    puts 'OK    [build] jekyll build succeeded'
  else
    warn 'ERROR [build] jekyll build FAILED — translating the trace:'
    sh 'ruby scripts/site_checks/build_outputs.rb --log tmp/build.log --json tmp/test-build.json' || true
    abort 'build failed (see tmp/build.log)'
  end
  sh 'ruby scripts/site_checks/build_outputs.rb --site _site --json tmp/test-build.json'
end

desc 'html-proofer on _site (offline: internal links, images, alt)'
task :proof do
  sh 'ruby scripts/site_checks/proof.rb --json tmp/test-proof.json'
end

desc 'Full CI gate: lint + build + proof'
task ci: %i[lint build proof] do
  puts '── ci: all three gates passed ──'
end

desc 'Lint + build, then serve locally (your usual serve command)'
task :serve do
  Rake::Task['lint'].invoke
  Rake::Task['build'].invoke
  puts '── serving at http://127.0.0.1:4000/courses (Ctrl-C to stop) ──'
  sh 'git submodule update --init --recursive' do |ok, _res|
    puts 'note: submodule update failed (continuing — submodules may already be present)' unless ok
  end
  sh 'JEKYLL_ENV=production bundle exec jekyll serve --baseurl /courses --watch --host 127.0.0.1 --port 4000'
end

# ---------- helpers ----------

def baseurl_from_config
  require 'yaml'
  config = YAML.safe_load(File.read('_config.yml'), permitted_classes: [Date, Time]) || {}
  "/#{config['baseurl'].to_s.sub(%r{\A/}, '')}"
rescue StandardError
  '/'
end
