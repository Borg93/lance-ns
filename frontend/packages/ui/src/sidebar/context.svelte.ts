import { getContext, setContext } from "svelte";

type Getter<T> = () => T;

export type SidebarStateProps = {
  /** reactive getter for the open state */
  open: Getter<boolean>;
  /** setter the provider wires to cookie persistence */
  setOpen: (open: boolean) => void;
};

/** The shared Sidebar context (shadcn-svelte, desktop-only — no mobile drawer).
 *  Holds open state and exposes a `state` string for the data-attributes the
 *  collapsible CSS keys off. */
class SidebarState {
  readonly props: SidebarStateProps;
  open = $derived.by(() => this.props.open());
  setOpen: (open: boolean) => void;
  state = $derived.by(() => (this.open ? "expanded" : "collapsed"));

  constructor(props: SidebarStateProps) {
    this.setOpen = props.setOpen;
    this.props = props;
  }

  toggle = () => this.setOpen(!this.open);
}

const SYMBOL_KEY = "scn-sidebar";

export function setSidebar(props: SidebarStateProps): SidebarState {
  return setContext(Symbol.for(SYMBOL_KEY), new SidebarState(props));
}

export function useSidebar(): SidebarState {
  return getContext(Symbol.for(SYMBOL_KEY));
}
