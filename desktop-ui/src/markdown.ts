import { Marked } from 'marked'
import DOMPurify from 'dompurify'

const parser = new Marked({ async: false, gfm: true, breaks: true, renderer: { html: () => '' } })
export function markdown(text: string): string {
  return DOMPurify.sanitize(parser.parse(text, { async: false }), {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'a', 'ul', 'ol', 'li', 'pre', 'code', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'hr', 'h1', 'h2', 'h3', 'h4'],
    ALLOWED_ATTR: ['href', 'title', 'class'],
  })
}
