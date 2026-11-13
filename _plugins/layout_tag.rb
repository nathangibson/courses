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

      case @variant
      when /\Aphoto-full\z/
        wrap_photo_full(html)
      else
        wrap_split(html, @variant)
      end
    end

    private

    def wrap_photo_full(html)
      %(<div class="layout-photo-full" markdown="1">\n#{html}\n</div>)
    end

    def wrap_split(html, variant)
      # DOM-based column split with content auto-assignment: parse the
      # converted HTML as a fragment and assign each TOP-LEVEL node to a
      # column. Nodes whose content is an image (an <img>, or a <p>/<div>
      # containing only an <img>) go to the image column; everything else to
      # the text column. No markers needed — author just writes markdown.
      require 'nokogiri'
      frag = Nokogiri::HTML.fragment(html)

      text_nodes = []
      image_nodes = []
      current = :text
      frag.children.each do |node|
        # explicit marker still wins if present
        if node.comment? && node.text =~ /COL:\s*image/
          current = :image
          next
        elsif node.comment? && node.text =~ /COL:\s*text/
          current = :text
          next
        end
        # kramdown often wraps markers + content in ONE <p> — split that <p>
        # at ANY COL comment, switching columns as the markers say. The
        # starting bucket is the outer current state.
        if node.element? && %w(p div).include?(node.name) &&
           !node.xpath('.//comment()[contains(., "COL:")]').empty?
          inner = current
          node.children.each do |child|
            if child.comment? && child.text =~ /COL:\s*image/
              inner = :image
              next
            elsif child.comment? && child.text =~ /COL:\s*text/
              inner = :text
              next
            end
            (inner == :image ? image_nodes : text_nodes) << child
          end
          current = inner
          next
        end
        col = image_only?(node) ? :image : current
        (col == :image ? image_nodes : text_nodes) << node
      end

      classes = ['layout-split']
      classes.concat(variant.split(/\s+/).reject { |v| v == 'split' || v.empty? })

      text_html = text_nodes.map(&:to_html).join("\n")
      image_html = image_nodes.map(&:to_html).join("\n")

      <<~HTML
        <div class="#{classes.join(' ')}">
          <div class="text">
        #{text_html}
          </div>
          <div class="image">
        #{image_html}
          </div>
        </div>
      HTML
    end

    # True if the node's content is just an image: an <img>, or a <p>/<div>
    # whose only meaningful child is an <img>.
    def image_only?(node)
      return false unless node.element?
      return true if node.name == 'img'
      return false unless %w(p div).include?(node.name)
      kids = node.children.reject { |c| c.text? && c.text.strip.empty? }
      kids.size == 1 && kids.first.name == 'img'
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
