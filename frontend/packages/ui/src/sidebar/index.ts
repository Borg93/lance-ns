import Root from "./sidebar.svelte";
import Provider from "./sidebar-provider.svelte";
import Trigger from "./sidebar-trigger.svelte";
import Rail from "./sidebar-rail.svelte";
import Inset from "./sidebar-inset.svelte";
import MenuButton from "./sidebar-menu-button.svelte";

export { useSidebar, setSidebar, type SidebarStateProps } from "./context.svelte.js";
export {
  sidebarMenuButtonVariants,
  type SidebarMenuButtonSize,
  type SidebarMenuButtonVariant,
} from "./sidebar-menu-button.svelte";

// Structural wrappers (header / content / footer / group / menu / menu-item)
// are plain `data-slot` elements inlined where they're used — they were
// one-line div/ul/li shells, so they don't earn their own components.
export {
  Root,
  Provider,
  Trigger,
  Rail,
  Inset,
  MenuButton,
  //
  Root as Sidebar,
  Provider as SidebarProvider,
  Trigger as SidebarTrigger,
  Rail as SidebarRail,
  Inset as SidebarInset,
  MenuButton as SidebarMenuButton,
};
