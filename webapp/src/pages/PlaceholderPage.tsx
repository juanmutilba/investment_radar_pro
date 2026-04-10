type Props = {
  title: string;
  description: string;
};

export function PlaceholderPage({ title, description }: Props) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      <p className="page-desc">{description}</p>
      <div className="card">
        <h2>En construcción</h2>
        <p className="msg-muted" style={{ margin: 0 }}>
          Este módulo está reservado en el menú y en las rutas. Cuando avancemos
          la fase, añadiremos páginas y servicios dedicados sin cambiar el layout
          general.
        </p>
      </div>
    </>
  );
}
