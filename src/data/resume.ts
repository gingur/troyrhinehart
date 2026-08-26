/**
 * Resume content, mirroring `public/resume.pdf`.
 *
 * This is the source of truth for the HTML resume at `/resume`. When the PDF is
 * refreshed, update this file in the same commit so the two stay in sync.
 *
 * NOTE: the phone number on the PDF is deliberately omitted here — the HTML page
 * is crawlable plain text, so email and LinkedIn are the contact channels on it.
 */
export const resume = {
  name: 'Troy Rhinehart',
  title: 'Principal Software Engineer',
  location: 'Mesa, AZ',
  email: 'troy.rhinehart@gmail.com',
  linkedin: {
    label: 'linkedin.com/in/troyrhinehart',
    href: 'https://www.linkedin.com/in/troyrhinehart',
  },
  pdf: '/resume.pdf',
  // Short, stable URL; the saved file still gets a self-describing name.
  pdfDownloadName: 'Troy-Rhinehart-Resume.pdf',
  summary:
    'Principal Software Engineer with 15+ years of experience in web application architecture and developer experience, including 3+ years integrating AI. Leads agentic engineering practices at Attentive and builds the internal tooling behind them. Spent 13 years at GoDaddy shipping AI platforms and site-building products for entrepreneurs while mentoring engineers and setting company-wide technical standards.',
  experience: [
    {
      role: 'Principal Software Engineer',
      company: 'Attentive',
      dates: 'Dec 2025 – Present',
      location: 'Remote (US)',
      highlights: [
        "Co-designed and built the agentic orchestration platform every Attentive engineer uses, anchoring the org's developer experience and agentic engineering practice.",
        "Redesigned Attentive's Tag, the browser event and metadata capture layer, as a fully schematized plugin architecture that AI can generate and manage.",
        'Launched the company Tech Radar and helped standardize RFC/RFD processes, Engineering Principles, and the agentic observability and agent testing framework.',
        'Eliminated flaky front-end tests and tuned CI infrastructure: success rates rose from 70% to over 90% and pipeline times fell up to 80%.',
      ],
    },
    {
      role: 'Software Engineer → Principal Software Engineer',
      company: 'GoDaddy',
      dates: 'Dec 2012 – Dec 2025',
      location: 'Tempe, AZ',
      highlights: [
        "Architected and delivered GoDaddy's AI platform: 11 providers, 80 models, one integration point for every product team.",
        "Built the WYSIWYG editor, publishing workflow, and widget and theme architecture behind Websites + Marketing, GoDaddy's site builder powering millions of customer sites.",
        'Led research, development, and technical direction for teams across the organization.',
        'Mentored junior engineers through code reviews and knowledge-sharing sessions.',
        'Shaped technology standards through the Principal Engineer Committee, its Steering Committee, the Tech Radar Techniques Committee, and guilds on React, Node, Micro Frontends, and Security.',
      ],
      note: 'Senior Software Engineer 2012–2017 · Principal Software Engineer 2017–2025 (L6 from 2021).',
    },
    {
      role: 'Junior Software Engineer',
      company: 'Village Voice Media',
      dates: 'Nov 2010 – Dec 2012',
      location: 'Phoenix, AZ',
      highlights: [
        'Built a single sign-on service that authenticated users across 13 regional websites.',
        'Shipped front-end and back-end features across the full development lifecycle.',
      ],
    },
  ],
  skills: [
    'Agentic engineering & AI orchestration',
    'Developer experience & CI health',
    'System architecture',
    'MFE architecture',
    'Node / JavaScript / TypeScript',
    'React',
    'Automated testing',
    'Technical mentoring',
  ],
  education: [
    {
      credential: 'B.S., Information Technology',
      institution: 'University of Phoenix',
      year: '2011',
    },
  ],
  awards: [
    'GoDaddy Innovation Award, Best Platform Improvement, 2023',
    'GoDaddy Innovation Award, Best Technology, 2021',
    'GoDaddy Innovation Award, 2014',
  ],
} as const;
