import type { Metadata } from "next";
import { FAQ_GROUPS as GROUPS, FaqItem } from "@/components/site/faq";
import { Cta, CtaBand, PageHero, Section } from "@/components/site/kit";
import { GITHUB } from "@/lib/site";

export const metadata: Metadata = {
  title: "FAQ · AgentCrucible",
  description: "Answers about connecting an agent, supported frameworks and models, data privacy, cost, statistics, CI and MCP server audits.",
};


export default function Faq() {
  return (
    <>
      <PageHero eyebrow="FAQ" title="Questions people actually ask"
        lead="Can't find yours? Open an issue on GitHub; good questions end up here.">
        <Cta href={`${GITHUB}/issues`}>Ask on GitHub</Cta>
      </PageHero>
      <Section>
        <div className="grid gap-12 lg:grid-cols-[220px_1fr]">
          <nav className="hidden lg:block">
            <div className="sticky top-24 space-y-1 text-[13.5px]">
              {GROUPS.map(([g]) => (
                <a key={g} href={`#${slug(g)}`} className="block rounded-lg px-3 py-1.5 text-mute hover:bg-white/5 hover:text-fg">{g}</a>
              ))}
            </div>
          </nav>
          <div className="space-y-12">
            {GROUPS.map(([g, qs]) => (
              <div key={g} id={slug(g)} className="scroll-mt-24">
                <h2 className="mb-4 text-[22px] font-semibold tracking-tight">{g}</h2>
                <div className="space-y-3">
                  {qs.map(([q, a]) => (
                    <FaqItem key={q} q={q} a={a} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Section>
      <CtaBand />
    </>
  );
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
