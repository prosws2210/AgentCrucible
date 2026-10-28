import { Nav } from "@/components/Nav";
import { Footer } from "@/components/site/Footer";

/** Marketing pages: shared nav and footer. The dashboard has its own shell. */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav />
      <main id="top" className="flex-1">{children}</main>
      <Footer />
    </>
  );
}
