/**
 * Resume content for the HTML page, factually aligned with `public/resume.pdf`.
 *
 * This is the source of truth for the HTML resume at `/resume`. The PDF is a
 * separately typeset document, so wording may differ while roles, dates, and
 * outcomes should stay aligned.
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
    'Principal Software Engineer with 15+ years building platforms, developer systems, and web products at scale. Leads agentic engineering at Attentive, building the orchestration, observability, testing, and browser foundations behind AI-assisted development. Previously spent 13 years at GoDaddy, architecting a unified AI platform and core site-builder systems used across millions of customer sites. Combines hands-on architecture with organization-wide technical standards, mentoring, and delivery improvement.',
  experience: [
    {
      role: 'Principal Software Engineer',
      company: 'Attentive',
      dates: 'Dec 2025 – Present',
      location: 'Remote (US)',
      highlights: [
        "Co-designed and shipped Attentive's shared agentic orchestration platform, now the foundation for AI-assisted engineering across the company.",
        'Eliminated flaky front-end tests and tuned CI infrastructure: success rates rose from 70% to over 90% and pipeline times fell up to 80%.',
        "Rebuilt Attentive's browser event and metadata layer as a schematized plugin architecture that AI can generate and manage.",
        'Launched the company Tech Radar and advanced RFC/RFD practices, Engineering Principles, agent observability, and agent testing.',
      ],
    },
    {
      role: 'Software Engineer → Principal Software Engineer',
      company: 'GoDaddy',
      dates: 'Dec 2012 – Dec 2025',
      location: 'Tempe, AZ',
      highlights: [
        "Architected GoDaddy's unified AI platform: 11 providers and 80 models behind one integration point for every product team.",
        'Built the editor, publishing workflow, and widget and theme architecture behind Websites + Marketing, powering millions of customer sites.',
        'Shaped technical standards through the Principal Engineer Committee, its Steering Committee, the Tech Radar Techniques Committee, and engineering guilds.',
        'Led research and delivery across the organization while mentoring engineers through code reviews and knowledge sharing.',
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
    'Agentic engineering & AI platforms',
    'Platform & system architecture',
    'Developer experience, CI & test reliability',
    'Web application architecture',
    'Technical strategy & standards',
    'TypeScript / Node / React',
    'Micro frontend architecture',
    'Mentoring & technical leadership',
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
