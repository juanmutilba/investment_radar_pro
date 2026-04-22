import { NavLink } from "react-router-dom";

type NavItem = {
  to: string;
  label: string;
  placeholder?: boolean;
  end?: boolean;
};

const ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/acciones-usa", label: "Acciones USA" },
  { to: "/acciones-argentina", label: "Acciones Argentina" },
  { to: "/cedears", label: "CEDEARs" },
  { to: "/bonos", label: "Bonos", placeholder: true },
  { to: "/opciones", label: "Opciones", placeholder: true },
  { to: "/futuros", label: "Futuros", placeholder: true },
  { to: "/alertas", label: "Alertas" },
  { to: "/cartera", label: "Cartera" },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <h1>Investment Radar</h1>
        <span>Panel de inversiones</span>
      </div>
      <nav className="sidebar__nav" aria-label="Principal">
        {ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={Boolean(item.end)}
            className={({ isActive }) =>
              [
                "sidebar__link",
                isActive ? "sidebar__link--active" : "",
                item.placeholder ? "sidebar__link--placeholder" : "",
              ]
                .filter(Boolean)
                .join(" ")
            }
          >
            {item.label}
            {item.placeholder ? " (pronto)" : ""}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
