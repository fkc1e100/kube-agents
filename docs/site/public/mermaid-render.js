// Client-side Mermaid rendering for kube-agents docs.
//
// Starlight's default handling shows ```mermaid blocks as syntax-highlighted
// code (via expressive-code). This script upgrades them to rendered SVG
// diagrams, adds an Expand button that pops the diagram into a full-viewport
// modal, and preserves the original source in a collapsible <details> block.
//
// Loaded via astro.config.mjs `head` config, so it runs on every page.

import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

const isDark = () => document.documentElement.dataset.theme === 'dark';

function mermaidConfig() {
  const dark = isDark();
  return {
    startOnLoad: false,
    theme: dark ? 'dark' : 'default',
    securityLevel: 'loose',
    flowchart: { htmlLabels: true, curve: 'basis' },
    themeVariables: dark
      ? {
          background: '#0f172a',
          primaryColor: '#1e293b',
          primaryTextColor: '#f1f5f9',
          primaryBorderColor: '#60a5fa',
          secondaryColor: '#1e1b4b',
          secondaryBorderColor: '#a78bfa',
          tertiaryColor: '#172554',
          tertiaryBorderColor: '#38bdf8',
          lineColor: '#94a3b8',
          textColor: '#f1f5f9',
          nodeBorder: '#60a5fa',
          clusterBkg: '#151f32',
          clusterBorder: '#334155',
          titleColor: '#93c5fd',
          edgeLabelBackground: '#151f32',
          fontFamily:
            "'Google Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        }
      : {
          background: '#ffffff',
          primaryColor: '#e8f0fe',
          primaryTextColor: '#202124',
          primaryBorderColor: '#1a73e8',
          secondaryColor: '#f3e8fd',
          secondaryBorderColor: '#9334e6',
          tertiaryColor: '#e6f4ea',
          tertiaryBorderColor: '#1e8e3e',
          lineColor: '#5f6368',
          textColor: '#202124',
          nodeBorder: '#1a73e8',
          clusterBkg: '#f8f9fa',
          clusterBorder: '#dadce0',
          titleColor: '#174ea6',
          edgeLabelBackground: '#ffffff',
          fontFamily:
            "'Google Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        },
    themeCSS: dark
      ? `
        .node rect, .node polygon, .node circle, .node path { stroke-width: 1.5px !important; }
        .nodeLabel, .nodeLabel p, .node .label { color: #f1f5f9 !important; fill: #f1f5f9 !important; }
        .edgeLabel, .edgeLabel p, .edgeLabel .label { color: #cbd5e1 !important; fill: #cbd5e1 !important; background-color: #151f32 !important; }
        .edgeLabel rect { fill: #151f32 !important; opacity: 0.95 !important; }
        .cluster rect { fill: #151f32 !important; stroke: #334155 !important; stroke-dasharray: 4 3 !important; }
        .cluster-label, .cluster-label p, .cluster-label .nodeLabel, .cluster text { color: #93c5fd !important; fill: #93c5fd !important; font-weight: 600 !important; }
      `
      : `
        .node rect, .node polygon, .node circle, .node path { stroke-width: 1.5px !important; }
        .nodeLabel, .nodeLabel p, .node .label { color: #202124 !important; fill: #202124 !important; }
        .edgeLabel, .edgeLabel p, .edgeLabel .label { color: #3c4043 !important; fill: #3c4043 !important; background-color: #ffffff !important; }
        .edgeLabel rect { fill: #ffffff !important; opacity: 0.95 !important; }
        .cluster rect { fill: #f8f9fa !important; stroke: #dadce0 !important; stroke-dasharray: 4 3 !important; }
        .cluster-label, .cluster-label p, .cluster-label .nodeLabel, .cluster text { color: #174ea6 !important; fill: #174ea6 !important; font-weight: 600 !important; }
      `,
  };
}

mermaid.initialize(mermaidConfig());

/**
 * Extract the mermaid source from an expressive-code <pre>. Naïve
 * textContent flattens everything onto one line because expressive-code
 * emits each source line as a separate <div class="ec-line"> with no
 * text-node newline between siblings — that breaks mermaid, which needs
 * real newlines to tokenize `subgraph`, `end`, and edge lines. Walk the
 * per-line divs and rejoin with '\n'.
 */
function extractMermaidSource(pre) {
  const lines = pre.querySelectorAll('.ec-line');
  if (lines.length) {
    return Array.from(lines)
      .map((line) => line.textContent || '')
      .join('\n')
      .trim();
  }
  return (pre.textContent || '').trim();
}

/**
 * Mermaid emits SVGs with intrinsic width/height attributes based on
 * the source diagram size, which means small diagrams stay small even
 * when their container is wide. Strip those and rely on the SVG's
 * viewBox + CSS `width: 100%` so the diagram scales to its container.
 * Keeps aspect ratio via viewBox.
 */
function makeSvgResponsive(svg) {
  svg.removeAttribute('width');
  svg.removeAttribute('height');
  svg.style.width = '100%';
  svg.style.height = 'auto';
  svg.style.maxWidth = '100%';
  return svg;
}

// Modal state — single shared overlay reused across every diagram on
// the page.
let modalRoot = null;

function ensureModal() {
  if (modalRoot) return modalRoot;

  modalRoot = document.createElement('div');
  modalRoot.className = 'mermaid-modal';
  modalRoot.setAttribute('role', 'dialog');
  modalRoot.setAttribute('aria-modal', 'true');
  modalRoot.setAttribute('aria-label', 'Enlarged diagram');
  modalRoot.hidden = true;

  const surface = document.createElement('div');
  surface.className = 'mermaid-modal-surface';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'mermaid-modal-close';
  closeBtn.setAttribute('aria-label', 'Close enlarged diagram');
  closeBtn.textContent = 'Close ✕';

  const stage = document.createElement('div');
  stage.className = 'mermaid-modal-stage';

  surface.appendChild(closeBtn);
  surface.appendChild(stage);
  modalRoot.appendChild(surface);
  document.body.appendChild(modalRoot);

  // Element that opened the modal — focus returns here on close so
  // keyboard and screen-reader users don't lose their place on the page.
  // (WCAG 2.4.3 / WAI-ARIA authoring practices for modal dialogs.)
  let triggerElement = null;

  const close = () => {
    modalRoot.hidden = true;
    stage.innerHTML = '';
    document.body.style.overflow = '';
    if (triggerElement) {
      triggerElement.focus();
      triggerElement = null;
    }
  };

  closeBtn.addEventListener('click', close);
  modalRoot.addEventListener('click', (e) => {
    if (e.target === modalRoot) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modalRoot.hidden) close();
  });

  modalRoot._open = (svgMarkup, triggerEl) => {
    triggerElement = triggerEl || document.activeElement;
    stage.innerHTML = svgMarkup;
    const svg = stage.querySelector('svg');
    if (svg) {
      // Different sizing from inline: fill whichever dimension hits first.
      // SVG's preserveAspectRatio="xMidYMid meet" (default) handles the
      // letterboxing, so a portrait diagram uses full height and a
      // landscape one uses full width.
      svg.removeAttribute('width');
      svg.removeAttribute('height');
      svg.style.width = '100%';
      svg.style.height = '100%';
      svg.style.maxWidth = '100%';
      svg.style.maxHeight = '100%';
      svg.style.display = 'block';
    }
    modalRoot.hidden = false;
    document.body.style.overflow = 'hidden';
    closeBtn.focus();
  };

  return modalRoot;
}

async function renderMermaidBlocks() {
  const blocks = document.querySelectorAll('pre[data-language="mermaid"]');
  if (!blocks.length) return;

  for (const [i, pre] of blocks.entries()) {
    const src = extractMermaidSource(pre);
    if (!src) continue;

    // The full expressive-code figure wraps the <pre>; keep that as the
    // "source" block so the copy button, syntax highlighting, and framing
    // survive when the user opens the <details>.
    const figure =
      pre.closest('figure') || pre.closest('.expressive-code') || pre;

    const container = document.createElement('div');
    container.className = 'mermaid-block not-content';

    const rendered = document.createElement('div');
    rendered.className = 'mermaid-rendered';

    // Expand button lives in the corner of the rendered frame.
    const expandBtn = document.createElement('button');
    expandBtn.type = 'button';
    expandBtn.className = 'mermaid-expand';
    expandBtn.setAttribute('aria-label', 'Enlarge diagram');
    expandBtn.title = 'Enlarge diagram';
    expandBtn.innerHTML =
      '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="currentColor">' +
      '<path d="M4 4h6v2H6v4H4V4zm10 0h6v6h-2V6h-4V4zM4 14h2v4h4v2H4v-6zm14 0h2v6h-6v-2h4v-4z"/>' +
      '</svg>';

    const details = document.createElement('details');
    details.className = 'mermaid-source';
    const summary = document.createElement('summary');
    summary.textContent = 'Show mermaid source';
    details.appendChild(summary);

    // Replace the raw figure with our container first, then move the
    // original figure inside <details> below the rendered diagram.
    figure.replaceWith(container);
    container.appendChild(rendered);
    rendered.appendChild(expandBtn);
    details.appendChild(figure);
    container.appendChild(details);

    try {
      const { svg, bindFunctions } = await mermaid.render(
        `kube-agents-mermaid-${i}-${Date.now()}`,
        src,
      );
      // Insert SVG before the expand button so button stays in the top
      // right when we position it absolutely.
      const svgHost = document.createElement('div');
      svgHost.className = 'mermaid-svg';
      svgHost.innerHTML = svg;
      rendered.insertBefore(svgHost, expandBtn);
      const svgEl = svgHost.querySelector('svg');
      if (svgEl) makeSvgResponsive(svgEl);
      if (bindFunctions) bindFunctions(svgHost);

      expandBtn.addEventListener('click', () => {
        ensureModal()._open(svgHost.innerHTML, expandBtn);
      });
    } catch (err) {
      // On render failure, drop the wrapper and restore the source block
      // so the user still sees something useful.
      console.warn('[mermaid-render] failed to render diagram', err);
      container.replaceWith(figure);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderMermaidBlocks);
} else {
  renderMermaidBlocks();
}
