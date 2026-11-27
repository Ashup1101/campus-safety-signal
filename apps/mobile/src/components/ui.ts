// One type and spacing scale for the app screens (v14 design pass): screen title, section title,
// card, and the pressed look. System fonts; weight and size carry the hierarchy, not color.
export const ui = {
  title: "text-2xl font-bold text-foreground dark:text-foreground-dark",
  section: "mb-2 mt-6 text-xl font-semibold text-foreground dark:text-foreground-dark",
  card: "mt-3 rounded-2xl bg-card p-4 dark:bg-card-dark",
  note: "text-sm leading-5 text-muted-foreground dark:text-muted-foreground-dark",
} as const;

/** Pressed look for Pressable: dims slightly, like iOS list rows and buttons. */
export const pressed = ({ pressed: down }: { pressed: boolean }) => ({ opacity: down ? 0.6 : 1 });
