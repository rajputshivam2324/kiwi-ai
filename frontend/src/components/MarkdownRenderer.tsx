import React, { useEffect, useRef } from 'react';
import { Marked } from 'marked';
import hljs from 'highlight.js';
import 'highlight.js/styles/atom-one-dark.css'; // Good looking dark theme
import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';


interface MarkdownRendererProps {
  content: string;
}

const markedInstance = new Marked();

// Custom code renderer to add header and copy button
const renderer = {
  code(token: any) {
    const code = token.text || '';
    const lang = token.lang || 'text';
    
    // Highlight the code
    let highlightedCode = code;
    try {
      if (lang && lang !== 'text' && hljs.getLanguage(lang)) {
        highlightedCode = hljs.highlight(code, { language: lang }).value;
      } else {
        highlightedCode = hljs.highlightAuto(code).value;
      }
    } catch (e) {
      console.warn("Highlight error:", e);
    } // fallback to raw code

    // We can't render React components directly into marked output string with event listeners,
    // so we render the structural HTML and attach event listeners via DOM manipulation in a useEffect.
    
    return `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-block-lang">${lang}</span>
          <button class="copy-btn copy-code-btn" data-code="${DOMPurify.sanitize(code).replace(/"/g, '&quot;')}">
            <span class="copy-icon-container">${Math.random().toString(36).substring(7)}</span>
            <span class="copy-text">Copy</span>
          </button>
        </div>
        <div class="code-block-body">
          <pre><code class="hljs language-${lang}">${highlightedCode}</code></pre>
        </div>
      </div>
    `;
  }
};

markedInstance.use({ renderer });

/**
 * Pre-process content to render LaTeX math expressions using KaTeX.
 * Handles both block ($$...$$) and inline ($...$) math.
 * Uses placeholder tokens to prevent marked from mangling the rendered HTML.
 */
function renderMathInContent(content: string): string {
  const placeholders: { token: string; html: string }[] = [];
  let placeholderIndex = 0;

  const createPlaceholder = (html: string): string => {
    const token = `%%MATH_PLACEHOLDER_${placeholderIndex++}%%`;
    placeholders.push({ token, html });
    return token;
  };

  // Step 1: Replace block math $$...$$ (including multiline)
  let processed = content.replace(/\$\$([\s\S]*?)\$\$/g, (_match, tex) => {
    try {
      const html = katex.renderToString(tex.trim(), {
        displayMode: true,
        throwOnError: false,
        trust: true,
      });
      return createPlaceholder(`<div class="math-block">${html}</div>`);
    } catch (e) {
      console.warn('KaTeX block render error:', e);
      return createPlaceholder(`<div class="math-block math-error"><code>${tex.trim()}</code></div>`);
    }
  });

  // Step 2: Replace inline math $...$ (single line, non-greedy)
  // Avoid matching $$ (already handled), currency like $100, or empty $$ 
  processed = processed.replace(/(?<!\$)\$(?!\$)(?!\d)((?:[^$\\]|\\.)+?)\$(?!\$)/g, (_match, tex) => {
    try {
      const html = katex.renderToString(tex.trim(), {
        displayMode: false,
        throwOnError: false,
        trust: true,
      });
      return createPlaceholder(`<span class="math-inline">${html}</span>`);
    } catch (e) {
      console.warn('KaTeX inline render error:', e);
      return createPlaceholder(`<span class="math-inline math-error"><code>${tex.trim()}</code></span>`);
    }
  });

  // Step 3: Parse markdown
  let html = markedInstance.parse(processed) as string;

  // Step 4: Restore placeholders
  for (const { token, html: mathHtml } of placeholders) {
    html = html.replace(token, mathHtml);
  }

  return html;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Re-run DOM setup on content change
  useEffect(() => {
    if (!containerRef.current) return;

    // We need to inject the SVG into buttons dynamically because the renderToString above 
    // lacks the exact dynamic nature, and we also want to handle clicks.
    const copyButtons = containerRef.current.querySelectorAll('.copy-code-btn');
    
    const handleCopy = async (e: Event) => {
      const btn = e.currentTarget as HTMLButtonElement;
      const code = btn.getAttribute('data-code');
      if (code) {
        try {
          // Decode HTML entities if necessary
          const textarea = document.createElement('textarea');
          textarea.innerHTML = code;
          const decodedCode = textarea.value;

          await navigator.clipboard.writeText(decodedCode);
          
          btn.classList.add('copied');
          btn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check w-3.5 h-3.5"><path d="M20 6 9 17l-5-5"/></svg>
            <span class="copy-text">Copied!</span>
          `;
          
          setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = `
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-clipboard w-3.5 h-3.5"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>
              <span class="copy-text">Copy</span>
            `;
          }, 2000);
        } catch (err) {
          console.error("Failed to copy:", err);
        }
      }
    };

    // Initialize content inside the copy buttons since I used random string placeholder
    copyButtons.forEach(btn => {
      btn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-clipboard w-3.5 h-3.5"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>
        <span class="copy-text">Copy</span>
      `;
      btn.addEventListener('click', handleCopy);
    });

    return () => {
      copyButtons.forEach(btn => btn.removeEventListener('click', handleCopy));
    };
  }, [content]);

  // Parse Markdown with math rendering, DOMPurify for security
  const rawHtml = renderMathInContent(content);
  const cleanHtml = DOMPurify.sanitize(rawHtml, {
    ADD_TAGS: ['math', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'msup', 'msub', 'mfrac', 'msqrt', 'mtext', 'mover', 'munder', 'munderover', 'mtable', 'mtr', 'mtd', 'mspace', 'annotation', 'span'],
    ADD_ATTR: ['target', 'class', 'data-code', 'xmlns', 'mathvariant', 'stretchy', 'fence', 'separator', 'lspace', 'rspace', 'displaystyle', 'scriptlevel', 'columnalign', 'encoding', 'aria-hidden', 'style', 'height', 'width', 'viewBox', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'd', 'x', 'y', 'rx', 'ry'],
  });

  return (
    <div 
      ref={containerRef}
      className="markdown-body" 
      dangerouslySetInnerHTML={{ __html: cleanHtml }} 
    />
  );
};
