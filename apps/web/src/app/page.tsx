import { redirect } from "next/navigation";

// The website is the IUPD console only; students and parents use the app.
export default function Home() {
  redirect("/console");
}
