# frozen_string_literal: true

# _plugins/layout_tag.rb
#
# Liquid block tag for markdown-only slide layouts.  Lets a slide author wrap
# ordinary markdown in a layout container without writing HTML:
#
#   {% layout split image-right %}
#   ## Heading
#
#   - text content
#   - more markdown
#
#   ![alt](../assets/img/x.jpg)
#   {% endlayout %}
#
# The tag renders its inner markdown with the standard markdown converter and
# wraps the result in  <div class="layout-<variant>"><div class="text">…</div>
# <div class="image">…</div></div>  — matching the .layout-* CSS classes in
# _sass/_custom.scss.
#
# The content is split into TEXT and IMAGE/MEDIA parts: any block that starts
# with an <img>/include producing an image goes to the .image column; everything
# else goes to .text.  Author marks columns explicitly with these markers:
#
#   {% layout split image-right %}
#   text…
#   {% col image %}
#   ![alt](x.jpg)
#   {% endlayout %}
#
# Supported variants (mapped onto the .layout-* CSS):
#   split            text left / image right  (layout-split)
#   split image-left                          (layout-split image-left)
#   split text-2-3                            (layout-split text-2-3)
#   split image-left-1-3                      (layout-split image-left-1-3)
#   split image-2-3                           (layout-split image-2-3)
#   photo-full       full-width photo under title (layout-photo-full)

module Jekyll
  class LayoutTagBlock < Liquid::Block
    def initialize(tag_name, markup, tokens)
      super
      @variant = markup.to_s.strip
    end

    def render(context)
      body = super
      site = context.registers[:site]
      converter = site.find_converter_instance(::Jekyll::Converters::Markdown)
      html = converter.convert(body)

      out = case @variant
            when /\Aphoto-full\z/
              wrap_photo_full(html)
            else
              wrap_split(html, @variant)
            end

      # The {% col %} sentinel can split kramdown HTML in the middle of a
      # <p>/<div>, leaving orphaned closing tags that revealify then escapes
      # into the slide as literal text (e.g. &lt;/p&gt;).  Strip orphaned
      # closers at column boundaries so nothing is left to escape.
      out.gsub(%r{&lt;/(p|div)&gt;\s*(?=(&lt;|$))}i, '')
         .gsub(%r{^\s*(&lt;/(p|div)&gt;)+\s*}i, '')
    end

    private

    def wrap_photo_full(html)
      %(<div class="layout-photo-full" markdown="1">\n#{html}\n</div>)
    end

    def wrap_split(html, variant)
      # Split the inner content at the <!--COL:image--> sentinel emitted by
      # the {% col image %} marker tag.
      text_parts = []
      image_parts = []
      current = :text
      html.each_line do |line|
        if line =~ /<!--COL:image-->/
          current = :image
          # keep any content sharing the line
          line = line.sub(/.*<!--COL:image-->/, '')
        elsif line =~ /<!--COL:text-->/
          current = :text
          line = line.sub(/.*<!--COL:text-->/, '')
        end
        (current == :image ? image_parts : text_parts) << line
      end

      classes = ['layout-split']
      classes.concat(variant.split(/\s+/).reject { |v| v == 'split' || v.empty? })

      <<~HTML
        <div class="#{classes.join(' ')}">
          <div class="text">
        #{text_parts.join}
          </div>
          <div class="image">
        #{image_parts.join}
          </div>
        </div>
      HTML
    end
  end
end

Liquid::Template.register_tag('layout', Jekyll::LayoutTagBlock)

# A marker tag used inside {% layout %} blocks to mark where the image column
# starts. Liquid would reject an unknown tag inside the block body, so it is
# registered here; it renders a sentinel comment that LayoutTagBlock splits on.
class LayoutColTag < Liquid::Tag
  def initialize(tag_name, markup, tokens)
    super
    @which = markup.to_s.strip
  end

  def render(_context)
    "<!--COL:#{@which}-->"
  end
end

Liquid::Template.register_tag('col', LayoutColTag)
