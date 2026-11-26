// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const BASE = '/kube-agents';
const FEEDBACK_FORM_URL =
  'https://docs.google.com/forms/d/e/1FAIpQLSfw5eGttWOrii7bvSUmALmRbqpxDRWKmdHoImEZZNe6hOtVtQ/viewform';

// Base URL matches the default GitHub Pages path
// (https://<owner>.github.io/kube-agents/) so relative links resolve
// identically in dev and in prod. Overridable via `--base` in a
// future deploy workflow if the site is served from a custom domain.
export default defineConfig({
  site: 'https://gke-labs.github.io',
  base: BASE,
  // Short link for people who cannot open an issue on GitHub (see the
  // contributing page's "Where to file issues"). Astro emits a static
  // meta-refresh page at <base>/feedback/ pointing at the form.
  redirects: {
    '/feedback': FEEDBACK_FORM_URL,
  },
  integrations: [
    starlight({
      title: 'kube-agents',
      description:
        'An open-source GKE operations teammate in the gke-labs organization: read-only fleet audits, upgrade readiness, and reviewed GitOps pull requests.',
      logo: undefined,
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/gke-labs/kube-agents',
        },
      ],
      editLink: {
        baseUrl:
          'https://github.com/gke-labs/kube-agents/edit/main/docs/site/',
      },
      // Client-side Mermaid renderer (light & dark theme aware). Upgrades
      // ```mermaid code blocks to SVG diagrams. See public/mermaid-render.js.
      head: [
        {
          tag: 'script',
          attrs: {
            type: 'module',
            src: `${BASE}/mermaid-render.js`,
          },
        },
      ],
      // Dual-theme palette (light default matching go/kube-agents-overview,
      // plus refined dark slate toggle) and splash landing page layout.
      customCss: ['./src/styles/theme.css'],
      expressiveCode: {
        themes: ['github-light', 'github-dark-default'],
      },
      // ThemeProvider defaults new visitors to light mode while keeping
      // Starlight's native ThemeSelect toggle active in the navbar.
      components: {
        ThemeProvider: './src/components/ThemeProvider.astro',
        Hero: './src/components/Hero.astro',
      },
      sidebar: [
        {
          label: 'Overview',
          items: [
            { label: 'Introduction', link: '/' },
            { label: 'Why kube-agents', link: '/overview/what-is-kube-agents/' },
            { label: 'Models, cost, and BYOT', link: '/overview/models-and-cost/' },
            { label: 'Trust, security, and autonomy', link: '/overview/trust-and-autonomy/' },
            { label: 'A day with kube-agents', link: '/overview/day-in-the-life/' },
            { label: 'Proactive autonomy', link: '/overview/proactive-autonomy/' },
            { label: 'Architecture', link: '/overview/architecture/' },
          ],
        },
        {
          label: 'Install',
          items: [
            { label: 'Prerequisites', link: '/install/prerequisites/' },
            { label: 'Quick start (GKE)', link: '/install/quickstart-gke/' },
            { label: 'First prompts', link: '/install/first-prompts/' },
            { label: 'Using kube-agents over MCP', link: '/install/mcp/' },
            { label: 'Slack app setup', link: '/install/slack-app/' },
            { label: 'Microsoft Teams app setup', link: '/install/teams-app/' },
            { label: 'Manual install', link: '/install/manual/' },
            { label: 'Helm and Kind', link: '/install/helm-and-kind/' },
            { label: 'GitLab as the GitOps forge', link: '/install/gitlab/' },
            { label: 'Bitbucket as the GitOps forge', link: '/install/bitbucket/' },
            { label: 'Gitea as the GitOps forge', link: '/install/gitea/' },
            { label: 'Upgrade', link: '/install/upgrade/' },
            { label: 'Recovering install.env', link: '/install/upgrade-recovery/' },
            { label: 'Uninstall', link: '/install/uninstall/' },
          ],
        },
        {
          label: 'Concepts',
          items: [{ autogenerate: { directory: 'concepts' } }],
        },
        {
          label: 'Skill catalog',
          link: '/skills/',
        },
        {
          label: 'Operator',
          items: [{ autogenerate: { directory: 'operator' } }],
        },
        {
          label: 'Deploy',
          items: [{ autogenerate: { directory: 'deploy' } }],
        },
        {
          label: 'Reference',
          items: [{ autogenerate: { directory: 'reference' } }],
        },
        {
          label: 'Contributing',
          link: '/contributing/',
        },
      ],
    }),
  ],
});
