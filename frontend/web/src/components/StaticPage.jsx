/* Privacy and Terms — static, self-contained, and honest about what this is.
 *
 * Two rules shaped this file:
 *
 * 1. It must not claim things the software does not do. Every statement below is
 *    checkable against the repository: there are no cookies (grep the source),
 *    no analytics, no accounts, and the only server-side personal data is the
 *    subscriber registry, which is an opt-in official contact list.
 * 2. It must be readable by a visitor AND by a crawler, so the text is rendered
 *    React (visible as ordinary content) and linked from the footer, and each
 *    page has its own single h1 and its own title/description.
 *
 * There is deliberately no cookie banner: there are no cookies to consent to.
 * Adding one would itself mean storing state about the visitor.
 */

const UPDATED = '2026-09-18'

function Section({ id, title, children }) {
  return (
    <section id={id} className="mt-10">
      <h2 className="display text-[clamp(1.3rem,2.4vw,1.9rem)]">{title}</h2>
      <div className="mt-3 space-y-3 text-[13px] leading-relaxed text-white/55">{children}</div>
    </section>
  )
}

function Privacy() {
  return (
    <>
      <h1 className="display mt-3 text-[clamp(2rem,4.6vw,3.4rem)]">Privacy</h1>
      <p className="mt-4 max-w-[70ch] text-[13px] leading-relaxed text-white/55">
        This page describes what the software does. It is written to be checked: everything stated
        here can be verified in the repository, and nothing here is a promise the code does not
        keep. Last updated {UPDATED}.
      </p>

      <Section id="collect" title="What is collected">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong className="text-white/75">Nothing about visitors, by default.</strong> A visit
            to this site sets no cookies, runs no analytics and loads no third-party trackers.
          </li>
          <li>
            <strong className="text-white/75">Location, only if you ask.</strong> The citizen brief
            has a “use my location” button. It calls the browser’s own Geolocation API and matches
            your position to the nearest zone locally, in your browser. The coordinates are never
            sent to this server or to anyone else.
          </li>
          <li>
            <strong className="text-white/75">Browser storage, not cookies.</strong> Your chosen
            city, your notification preferences and your basemap choice are kept in{' '}
            <code>localStorage</code> on your device. They never leave it, and clearing site data
            removes them.
          </li>
          <li>
            <strong className="text-white/75">A phone number, if you are enrolled as an official
            contact.</strong> The warning registry holds phone numbers, names, ward assignments and
            roles — for people who have been added to receive heat alerts. That list is readable only
            with an administrative token, and phone numbers are redacted even then.
          </li>
        </ul>
      </Section>

      <Section id="use" title="How it is used, and how long it is kept">
        <p>
          Registry data is used for one purpose: sending heat warnings to the people who opted in to
          receive them. Recipients are resolved by ward; the number and its ward are stored in a CSV
          in this deployment until you ask for removal.
        </p>
        <p>
          Sending “STOP” (or being removed by an operator) marks the entry as opted out
          immediately — opted-out numbers receive no further messages, including from later
          dispatches.
        </p>
      </Section>

      <Section id="third-parties" title="Third parties">
        <p>
          This site loads map tiles, terrain and typefaces from the providers listed on the landing
          page (Esri, OpenStreetMap, OpenTopoMap, Re:Earth, Google Fonts). Those requests carry your
          IP address and browser headers to those providers, as any web request does; they set no
          cookies here. Weather data is fetched from Open-Meteo.
        </p>
        <p>
          SMS and WhatsApp delivery, when enabled, is handled by Twilio. If you receive a message,
          your number was shared with Twilio for the purpose of delivering it.
        </p>
      </Section>

      <Section id="rights" title="Access, correction and removal">
        <p>
          To be removed from the registry, reply STOP to any message, or ask an operator to remove
          the entry. To ask what is held about your number, contact whoever operates this deployment
          — the repository does not fix an operator identity, so this page deliberately does not
          invent one (see “Business details” in the Terms).
        </p>
      </Section>

      <Section id="children" title="Children">
        <p>
          HeatShield does not create accounts and does not knowingly collect information from
          children. The warning registry is an adult contact list for officials and enrolled
          recipients.
        </p>
      </Section>
    </>
  )
}

function Terms() {
  return (
    <>
      <h1 className="display mt-3 text-[clamp(2rem,4.6vw,3.4rem)]">Terms of use</h1>
      <p className="mt-4 max-w-[70ch] text-[13px] leading-relaxed text-white/55">
        Short version: HeatShield is a prototype that helps people reason about heat risk. It is not
        an official warning service, and it is not a substitute for one. Last updated {UPDATED}.
      </p>

      <Section id="not-official" title="This is not an official advisory">
        <p>
          HeatShield is an independent, open-source decision-support tool. It is not affiliated with
          the India Meteorological Department, the Kolkata Municipal Corporation, any state or
          national health authority, or any other government body. It does not issue official
          warnings, and nothing here should be presented as one.
        </p>
      </Section>

      <Section id="estimates" title="What the numbers are, and what they are not">
        <p>
          Risk scores, WBGT values and exposure estimates are derived from forecast weather data and
          census statistics using published methods. They are estimates with real uncertainty:
          weather forecasts change, ward boundaries simplify terrain, and census figures are from
          2011. Every screen states the forecast run it is showing, and the demo screens are
          labelled synthetic wherever they appear.
        </p>
        <p>
          HeatShield does not measure anything physically. It does not know your medical
          circumstances, your housing, or your exposure at this moment.
        </p>
      </Section>

      <Section id="decisions" title="Do not rely on this for safety decisions">
        <p>
          Use official advisories and your own judgement for decisions that affect health or safety.
          If the software is wrong, or unavailable, or its data is stale, it will not tell you
          everything you need to know — and it must not be the only thing you rely on. The interface
          is built to say “I don’t have data” rather than to guess, but an outage is still an outage.
        </p>
      </Section>

      <Section id="licence" title="Licence and reuse">
        <p>
          The source is published under the licence in the repository (see{' '}
          <a
            className="underline decoration-white/20 underline-offset-4"
            href="https://github.com/Soumallo99/Heatshield/blob/main/LICENSE"
            rel="noopener noreferrer"
            target="_blank"
          >
            LICENSE
          </a>
          ). Underlying datasets keep their own terms — OpenStreetMap data is ODbL, OpenTopoMap is
          CC BY-SA, and the census data follows Government of India terms. Attribution obligations
          are listed on the landing page and in THIRD-PARTY.md.
        </p>
      </Section>

      <Section id="availability" title="Availability and changes">
        <p>
          This deployment is provided as-is, with no availability guarantee and no warranty. It may
          be unavailable during data refreshes, may change without notice, and may be withdrawn.
        </p>
      </Section>

      <Section id="operator" title="Business details">
        <p>
          There is no company behind this deployment: it is an open-source student project. There is
          nothing to sell, no subscription and no payment of any kind — which is why there is no
          refund policy on this site. If you are operating this software on behalf of an
          organisation, the operator identity, contact address and governing jurisdiction belong in
          this section, and only the operator can supply them.
        </p>
      </Section>

      <Section id="contact" title="Contact">
        <p>
          Issues and questions:{' '}
          <a
            className="underline decoration-white/20 underline-offset-4"
            href="https://github.com/Soumallo99/Heatshield/issues"
            rel="noopener noreferrer"
            target="_blank"
          >
            the repository issue tracker
          </a>
          .
        </p>
      </Section>
    </>
  )
}

function NotFound() {
  return (
    <>
      <p className="eyebrow mt-3">404</p>
      <h1 className="display mt-2 text-[clamp(2rem,4.6vw,3.4rem)]">That page does not exist</h1>
      <p className="mt-4 max-w-[60ch] text-[13px] leading-relaxed text-white/55">
        The link may be old, or mistyped. Everything HeatShield publishes is reachable from the
        pages below.
      </p>
      <ul className="mt-8 grid gap-3 sm:grid-cols-2">
        {[
          ['Overview', '#/', 'What HeatShield is, and where its data comes from'],
          ['Operations dashboard', '#/dashboard', 'Live heat risk for all 141 Kolkata wards'],
          ['Citizen brief', '#/phone', 'Your local risk and what to do about it'],
          ['Heat Risk Demo', '#/demo', 'Labelled synthetic scenarios, works offline'],
        ].map(([label, href, description]) => (
          <li key={href}>
            <a href={href} className="panel block p-5 transition hover:border-white/25">
              <span className="text-[14px] text-white/85">{label}</span>
              <span className="mt-1 block text-[12px] text-white/62">{description}</span>
            </a>
          </li>
        ))}
      </ul>
    </>
  )
}

const PAGES = { privacy: Privacy, terms: Terms, notfound: NotFound }

/** `page` is one of "privacy" | "terms" | "notfound". */
export default function StaticPage({ page = 'privacy' }) {
  const Content = PAGES[page] || NotFound
  return (
    <main className="mx-auto max-w-[900px] px-6 py-16">
      <a
        href="#/"
        className="text-[12px] text-white/60 underline decoration-white/15 underline-offset-4 transition hover:text-white/70"
      >
        ← Back to overview
      </a>
      <article className="mt-6">{Content()}</article>
      <nav aria-label="Legal and help" className="mt-14 border-t border-white/10 pt-6 text-[12px] text-white/60">
        <a className="underline decoration-white/15 underline-offset-4 hover:text-white/70" href="#/privacy">
          Privacy
        </a>
        <span className="px-2">·</span>
        <a className="underline decoration-white/15 underline-offset-4 hover:text-white/70" href="#/terms">
          Terms
        </a>
        <span className="px-2">·</span>
        <a className="underline decoration-white/15 underline-offset-4 hover:text-white/70" href="#/#sources">
          Sources
        </a>
      </nav>
    </main>
  )
}
