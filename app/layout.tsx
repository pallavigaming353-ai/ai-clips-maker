import type { Metadata } from "next";
export const metadata: Metadata = { title: "AI Clips Maker", description: "Create video clips with AI" };
export default function RootLayout({ children }: { children: React.ReactNode }) { return <html lang="en"><body style={{margin:0,background:"#080e1b",color:"#edf2ff",fontFamily:"system-ui,sans-serif"}}>{children}</body></html>; }
