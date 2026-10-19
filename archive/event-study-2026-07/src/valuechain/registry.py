"""
Structured registry of value-chain chokepoints, keywords, tickers, and
qualitative theses, extracted from the research in data/valuechain/*.md.
This is the knowledge base the news-tagging engine matches against — keep
it in sync with the markdown (markdown is the source of truth / detail,
this is the queryable summary consumed by the dashboard).

Each entry: one chokepoint/theme with:
  keywords    = text patterns to match news against
  thesis_90d  = the qualitative thesis for what happens over ~90 days
                (a bearish mechanism for exposed names, a bullish one for
                beneficiaries) — this is the "connect the dots" narrative,
                not a statistical claim
  companies   = tickers tagged by role + inherited direction:
    chokepoint   = where the disruption originates (bearish for it)
    direct       = 1-hop dependent, commonly named in the same news story (bearish)
    indirect     = 2+ hop dependent, rarely named explicitly (bearish, slow-to-price —
                   the whole point of this project)
    beneficiary  = gains from the disruption (bullish)
"""

_DIRECTION_BY_ROLE = {"chokepoint": "bearish", "direct": "bearish", "indirect": "bearish", "beneficiary": "bullish"}


def _companies(*pairs):
    """pairs: (ticker, role) or (ticker, role, direction_override)."""
    out = []
    for p in pairs:
        ticker, role = p[0], p[1]
        direction = p[2] if len(p) > 2 else _DIRECTION_BY_ROLE[role]
        out.append({"ticker": ticker, "role": role, "direction": direction})
    return out


REGISTRY = {
    "semiconductors": [
        {
            "chokepoint": "TSMC advanced node / Taiwan fabrication",
            "keywords": ["TSMC", "Taiwan Semiconductor", "advanced node", "3nm", "2nm", "foundry", "Taiwan earthquake", "Taiwan Strait"],
            "thesis_90d": {
                "bearish": "Directa: un corte de producción en TSMC (terremoto, escasez, restricción de exportación) retrasa entregas a sus clientes fabless dentro del trimestre — Apple/Nvidia/Broadcom/AMD/Qualcomm dependen de un único proveedor sin capacidad de sustitución rápida. Indirecta: fabricantes de productos finales (electrónica de consumo, autos con chips avanzados) sienten el apriete 1-2 trimestres después, cuando se agota el inventario buffer.",
                "bullish": "Samsung Foundry y UMC son los únicos con capacidad remanente para absorber pedidos desviados de TSMC — un cliente que reasigna producción por seguridad de suministro es una tesis alcista de 90 días para ellos, aunque con calidad/yield inferior.",
            },
            "companies": _companies(
                ("TSM", "chokepoint"), ("AAPL", "direct"), ("NVDA", "direct"), ("AVGO", "direct"), ("AMD", "direct"), ("QCOM", "direct"),
                ("UMC", "beneficiary"), ("005930.KS", "beneficiary"),
            ),
        },
        {
            "chokepoint": "ASML EUV lithography equipment",
            "keywords": ["ASML", "EUV", "lithography", "chip equipment export", "Netherlands chip"],
            "thesis_90d": {
                "bearish": "Directa: una restricción de exportación de equipos EUV de ASML a un fab específico frena directamente la capacidad de ese fab de subir a nodos más avanzados dentro del trimestre. Indirecta: los clientes de ese fab (no ASML mismo) ven presión de oferta 1-2 trimestres después.",
            },
            "companies": _companies(("ASML", "chokepoint"), ("TSM", "direct"), ("005930.KS", "direct"), ("INTC", "direct")),
        },
        {
            "chokepoint": "Auto-grade MCU/discretes (Renesas, NXP, Infineon, Nexperia, STMicro)",
            "keywords": ["Renesas", "NXP", "Infineon", "Nexperia", "STMicro", "microcontroller shortage", "auto chip shortage"],
            "thesis_90d": {
                "bearish": "Directa: incendio/disrupción en una de estas fábricas fuerza a Ford/GM/Toyota/Honda a parar líneas de producción dentro de 30-60 días (patrón repetido: Renesas 2021, Texas 2021, Nexperia 2025). Indirecta: Stellantis y otros con menor concentración en estos proveedores sienten el apriete de precio con 60-90 días de retraso vía sus Tier-1 compartidos.",
            },
            "companies": _companies(
                ("6723.T", "chokepoint"), ("NXPI", "chokepoint"), ("IFX.DE", "chokepoint"), ("STM", "chokepoint"),
                ("F", "direct"), ("GM", "direct"), ("TM", "direct"), ("HMC", "direct"), ("STLA", "indirect"),
            ),
        },
        {
            "chokepoint": "China export controls on chips (US retaliation cycle)",
            "keywords": ["chip export controls", "China entity list", "BIS export", "H20", "H100", "chip ban"],
            "thesis_90d": {
                "bearish": "Directa: cada ronda de controles de exportación (EE.UU.→China o represalia China→EE.UU.) le corta a Nvidia/AMAT/Lam/KLA/ASML una porción de sus ventas a China dentro del mismo trimestre fiscal — ya pasó 4 veces (ago-2022, oct-2022, 2024, abr-2025) con cargos de cientos de millones a $5.5B cada vez.",
            },
            "companies": _companies(("NVDA", "direct"), ("AMAT", "direct"), ("LRCX", "direct"), ("KLAC", "direct"), ("ASML", "direct")),
        },
    ],
    "automotive": [
        {
            "chokepoint": "EV battery supply chain (CATL/BYD/LG/Panasonic + lithium/cobalt refining)",
            "keywords": ["CATL", "battery supply", "lithium refining", "cobalt refining", "EV battery shortage", "Ultium", "BlueOval"],
            "thesis_90d": {
                "bearish": "Directa: Tesla/GM/Ford dependen de JVs de batería (Ultium, BlueOval) cuya salud financiera ya es frágil (varias unwinds en 2025-2026) — una disrupción de celdas frena producción de EVs específicos dentro del trimestre. Indirecta: la refinación de litio/cobalto está 30%+ en manos chinas aunque se mine en otro lado, así que un control de exportación golpea con 1-2 trimestres de retraso vía el costo de celda.",
                "bullish": "Albemarle/Glencore (productores no-chinos de litio/cobalto) se benefician como alternativa de sourcing si hay fricción con refinación china — tesis de 90 días si se anuncia diversificación de cadena de suministro.",
            },
            "companies": _companies(
                ("300750.SZ", "chokepoint"), ("1211.HK", "chokepoint"), ("373220.KS", "chokepoint"), ("6752.T", "chokepoint"),
                ("TSLA", "direct"), ("GM", "direct"), ("F", "direct"), ("ALB", "beneficiary"), ("GLEN.L", "beneficiary"),
            ),
        },
        {
            "chokepoint": "Ukraine wire harness manufacturing",
            "keywords": ["wire harness", "Leoni", "Fujikura", "Ukraine auto parts", "Ukraine supplier"],
            "thesis_90d": {
                "bearish": "Directa: un arnés de cables no se puede stockear ni transportar por aire — una disrupción en las plantas de Leoni/Fujikura en Ucrania para líneas de ensamblaje de VW/BMW/Mercedes/Ford dentro de DÍAS, no meses (ya ocurrió en feb-2022). Es de las tesis bajistas de materialización más rápida de todo el registro.",
            },
            "companies": _companies(("VWAGY", "direct"), ("BMWYY", "direct"), ("MBGYY", "direct"), ("F", "direct")),
        },
        {
            "chokepoint": "China EV overcapacity / tariffs",
            "keywords": ["BYD", "Chinese EV export", "China EV overcapacity", "EV tariff", "Section 232 auto"],
            "thesis_90d": {
                "bearish": "Directa/estructural (no un shock puntual): la sobrecapacidad china (5-10M vehículos/año) y el precio de BYD (hasta 1/3 de un EV occidental comparable) presionan márgenes de GM/Ford/Stellantis/VW de forma continua — no es un evento de 90 días sino un viento de frente persistente que se acelera con cada anuncio de expansión de BYD a un nuevo mercado.",
            },
            "companies": _companies(("1211.HK", "chokepoint"), ("GM", "direct"), ("F", "direct"), ("STLA", "direct"), ("VWAGY", "direct")),
        },
    ],
    "pharma_biotech": [
        {
            "chokepoint": "WuXi AppTec / BIOSECURE Act / 1260H list",
            "keywords": ["WuXi", "BIOSECURE", "1260H", "CDMO China", "Pentagon blacklist biotech"],
            "thesis_90d": {
                "bearish": "Directa: Eli Lilly/Merck con exposición a WuXi como CDMO sole-source enfrentan riesgo de transferencia tecnológica costosa (años, no 90 días) si BIOSECURE se aplica en serio — pero el IMPACTO EN EL TITULO de WuXi mismo (2359.HK) es inmediato ante cada headline de listado/demanda. Indirecta: biotechs pequeñas no nombradas que también usan WuXi sufren el mismo riesgo sin que se note hasta su próximo 10-Q.",
                "bullish": "Lonza y Samsung Biologics son los CDMOs alternativos con capacidad para absorber contratos que huyan de WuXi — cada headline negativo para WuXi es, con semanas de retraso, una tesis alcista para ellos vía anuncios de nuevos contratos.",
            },
            "companies": _companies(
                ("2359.HK", "chokepoint"), ("2269.HK", "chokepoint"), ("LLY", "direct"), ("MRK", "direct"),
                ("LONN.SW", "beneficiary"), ("005930.KS", "beneficiary"),
            ),
        },
        {
            "chokepoint": "API manufacturing concentration (China/India)",
            "keywords": ["API shortage", "generic drug shortage", "FDA warning letter", "drug plant shutdown"],
            "thesis_90d": {
                "bearish": "Directa: una carta de advertencia de la FDA a una planta de API en India/China (ej. caso Intas 2023) puede cortar el suministro de un genérico específico dentro de semanas — Teva/Viatris/Hikma operan con márgenes finos, así que el impacto de ingresos es rápido y desproporcionado al tamaño del evento.",
            },
            "companies": _companies(("TEVA", "direct"), ("VTRS", "direct"), ("HIKMA.L", "direct")),
        },
        {
            "chokepoint": "Pharma tariffs / drug pricing policy (Section 232, IRA Medicare negotiation)",
            "keywords": ["pharma tariff", "drug pricing", "Medicare negotiation", "most favored nation pricing", "MFN drug"],
            "thesis_90d": {
                "bearish": "Directa: farmacéuticas con manufactura fuera de EE.UU. (Novartis, Roche, europeas/japonesas) absorben el arancel Section 232 dentro del trimestre salvo que negocien exención (como hizo Pfizer a cambio de precios MFN) — el patrón ya es conocido, así que el mercado reacciona el mismo día del anuncio de arancel.",
                "bullish": "Vertex (100% manufactura en EE.UU.) y AbbVie quedan estructuralmente protegidas de cualquier arancel — cada nuevo anuncio de arancel farmacéutico es relativamente alcista para ellas vs. pares con exposición internacional.",
            },
            "companies": _companies(("PFE", "direct"), ("NVS", "direct"), ("RHHBY", "direct"), ("VRTX", "beneficiary"), ("ABBV", "beneficiary")),
        },
    ],
    "agriculture": [
        {
            "chokepoint": "China soybean/ag trade retaliation",
            "keywords": ["soybean tariff", "China soybean", "ag trade war", "soybean export"],
            "thesis_90d": {
                "bearish": "Directa: un arancel/represalia china a la soja golpea a ADM/Bunge en el trimestre en curso vía volumen desviado a Brasil (patrón 2018-2019, todavía no revertido del todo aunque haya deshielo comercial en 2026). Indirecta: Deere/AGCO sienten la caída de ingreso agrícola 1-2 trimestres después vía menor demanda de maquinaria.",
            },
            "companies": _companies(("ADM", "direct"), ("BG", "direct"), ("DE", "indirect")),
        },
        {
            "chokepoint": "Potash/fertilizer supply (Canada/Russia/Belarus)",
            "keywords": ["potash", "Belaruskali", "Uralkali", "fertilizer sanctions", "Canpotex"],
            "thesis_90d": {
                "bearish": "Directa: una sanción o disrupción de exportación de potasa rusa/bielorrusa aprieta oferta global dentro del trimestre — Nutrien/Mosaic (potasa) suben de precio pero también enfrentan escrutinio legal por coordinación de precios.",
                "bullish": "CF Industries (nitrógeno, ligado a gas natural barato de EE.UU., no a potasa) se beneficia de forma independiente cuando cualquier fertilizante sube de precio en general — vale la pena distinguir nitrógeno de potasa/fosfato en la tesis.",
            },
            "companies": _companies(("NTR", "chokepoint"), ("MOS", "chokepoint"), ("CF", "beneficiary")),
        },
        {
            "chokepoint": "Black Sea grain corridor",
            "keywords": ["Black Sea grain", "Ukraine wheat export", "grain corridor"],
            "thesis_90d": {
                "bearish": "Indirecta: un bloqueo del corredor del Mar Negro sube precios globales de trigo, lo cual beneficia márgenes de trading de ADM/Bunge en el corto plazo pero perjudica a importadores netos — la dirección neta depende de si la empresa es originadora u compradora, hay que leer el mix geográfico específico antes de asumir bajista u alcista.",
            },
            "companies": _companies(("ADM", "indirect"), ("BG", "indirect")),
        },
    ],
    "metals_mining_rare_earths": [
        {
            "chokepoint": "China rare earth export controls",
            "keywords": ["rare earth export", "China rare earth", "NdPr magnet", "heavy rare earth", "REE licensing"],
            "thesis_90d": {
                "bearish": "Directa: cada apriete de licencias de tierras raras pesadas (abr-2025, oct-2025) corta el suministro de imanes NdPr a Ford/GM/Tesla y a contratistas de defensa (Lockheed, RTX, Northrop) — ya causó el cierre de la planta Ford Chicago Explorer en 2025 dentro de semanas del anuncio. Indirecta: Qorvo/Skyworks (electrónica de defensa GaAs/GaN) sienten el apriete 1-2 trimestres después vía sus propios proveedores.",
                "bullish": "MP Materials/USA Rare Earth/Lynas son los beneficiarios directos de cualquier headline de control de exportación china — history muestra +8% a +250% de revalorización en ventanas de 90 días cuando se anuncia re-shoring (aunque China ya empezó a sancionarlos directamente en 2026, lo cual complica la tesis alcista pura).",
            },
            "companies": _companies(
                ("MP", "beneficiary"), ("USAR", "beneficiary"), ("LYC.AX", "beneficiary"),
                ("F", "direct"), ("GM", "direct"), ("TSLA", "direct"), ("LMT", "direct"), ("RTX", "direct"), ("NOC", "direct"),
                ("GEV", "indirect"), ("QRVO", "indirect"), ("SWKS", "indirect"),
            ),
        },
        {
            "chokepoint": "Gallium/germanium/graphite export controls",
            "keywords": ["gallium export", "germanium export", "graphite export control", "China critical minerals ban"],
            "thesis_90d": {
                "bearish": "Directa: Coherent/Wolfspeed dependen de germanio/galio para óptica de defensa y semiconductores — un control de exportación chino ya causó una caída de exportación de 96% (jul-oct 2023) y subida de precio de 68%, con impacto de costo visible en 1-2 trimestres.",
            },
            "companies": _companies(("COHR", "direct"), ("WOLF", "direct")),
        },
        {
            "chokepoint": "Copper supply (Chile/Peru)",
            "keywords": ["Codelco", "copper mine", "Chile copper", "Peru copper"],
            "thesis_90d": {
                "bearish": "Directa: una disrupción minera en Chile/Perú (huelga, problema operativo en Codelco) reduce oferta global de cobre y sube el costo de insumo para toda la cadena eléctrica/EV — pero para Freeport-McMoRan y Southern Copper mismos, si ELLOS no son los afectados, es más bien una tesis alcista de precio.",
            },
            "companies": _companies(("FCX", "direct"), ("SCCO", "direct")),
        },
    ],
    "retail_apparel": [
        {
            "chokepoint": "Apparel/footwear tariffs (Vietnam/China/Bangladesh)",
            "keywords": ["apparel tariff", "footwear tariff", "Vietnam tariff", "Section 122 tariff", "de minimis"],
            "thesis_90d": {
                "bearish": "Directa: Nike (Vietnam ~44%) y Target (China-heavy) absorben el costo de un arancel nuevo dentro del mismo trimestre como importadores de registro — el cliff de expiración de Section 122 el 24-jul-2026 es un catalizador con fecha exacta dentro de la ventana de 90 días. Indirecta: Walmart/Gap, ya diversificados, sienten mucho menos el mismo shock.",
            },
            "companies": _companies(("NKE", "direct"), ("TGT", "direct"), ("COLM", "direct"), ("UAA", "direct"), ("WMT", "indirect"), ("GPS", "indirect")),
        },
        {
            "chokepoint": "UFLPA Xinjiang cotton bans",
            "keywords": ["UFLPA", "Xinjiang cotton", "forced labor import ban"],
            "thesis_90d": {
                "bearish": "Directa: cada adición a la lista de entidades UFLPA congela envíos específicos sin aviso previo — Nike/Gap con trazabilidad incompleta de su cadena de algodón pueden ver detenciones de aduana dentro de semanas del anuncio.",
            },
            "companies": _companies(("NKE", "direct"), ("GPS", "direct")),
        },
    ],
    "telecom": [
        {
            "chokepoint": "Submarine cable sabotage/cuts",
            "keywords": ["submarine cable cut", "undersea cable", "Baltic Sea cable", "Red Sea cable"],
            "thesis_90d": {
                "bearish": "Directa: un corte de cable submarino ahora golpea directamente a Google/Meta/Microsoft/Amazon (dueños de ~90% de la capacidad transatlántica) en capex/outage, no solo a las telcos — el mercado todavía subestima esta transmisión porque piensa 'cable = problema de telco' cuando ya es 'cable = problema de hyperscaler'.",
            },
            "companies": _companies(("GOOGL", "direct"), ("META", "direct"), ("MSFT", "direct"), ("AMZN", "direct"), ("NOK", "direct")),
        },
        {
            "chokepoint": "Starlink/SpaceX (SPCX)",
            "keywords": ["Starlink", "SpaceX", "SPCX", "T-Satellite", "direct-to-cell"],
            "thesis_90d": {
                "bearish": "Directa: desde el IPO de SpaceX (jun-2026), cualquier declaración de Musk o disrupción de Starlink ahora se transmite directo a SPCX como ticker líquido — antes solo se podía tradear indirecto vía TSLA.",
                "bullish": "T-Mobile/AT&T/Verizon se benefician de las alianzas direct-to-cell con Starlink (ingreso adicional de $10/mes por usuario) — cada expansión de cobertura es alcista para el carrier asociado.",
            },
            "companies": _companies(("SPCX", "chokepoint", "bearish"), ("TMUS", "beneficiary"), ("T", "beneficiary"), ("VZ", "beneficiary"), ("AMZN", "beneficiary"), ("ETL.PA", "beneficiary")),
        },
        {
            "chokepoint": "RAN vendor concentration (Huawei/ZTE ban, Ericsson/Nokia)",
            "keywords": ["Huawei ban", "ZTE ban", "rip and replace", "Ericsson Nokia RAN"],
            "thesis_90d": {
                "bearish": "Directa: AT&T (100% Ericsson desde 2023) y Verizon (Samsung/Ericsson) tienen concentración de proveedor único — un problema de entrega o calidad en Ericsson les pega sin alternativa rápida dentro del mismo trimestre, ya que Open RAN fracasó en diversificar la cadena.",
            },
            "companies": _companies(("T", "direct"), ("VZ", "direct"), ("ERIC", "chokepoint"), ("NOK", "chokepoint")),
        },
    ],
    "financials": [
        {
            "chokepoint": "Fed policy / FOMC surprise",
            "keywords": ["FOMC", "Fed rate decision", "Fed Chair Powell", "Jerome Powell", "Federal Reserve rate"],
            "thesis_90d": {
                "bearish": "Directa: un giro hawkish sorpresivo de la Fed sube el costo de depósitos de bancos regionales (PNC/KeyCorp/Zions) con 3-4 TRIMESTRES de rezago incluso después de que la Fed pare de subir tasas (el 'deposit beta' sigue subiendo) — el impacto no es inmediato, es acumulativo.",
                "bullish": "JPM/BAC (money-center) están protegidos por ingresos de trading/banca de inversión que compensan cualquier compresión de margen — son relativamente alcistas vs. regionales ante el mismo shock de tasas.",
            },
            "companies": _companies(("JPM", "direct", "bullish"), ("BAC", "direct", "bullish"), ("WFC", "direct"), ("PNC", "indirect"), ("KEY", "indirect"), ("ZION", "indirect")),
        },
        {
            "chokepoint": "Payment rail / clearinghouse outage or sanction (Fedwire, SWIFT, Visa/MA)",
            "keywords": ["Fedwire outage", "SWIFT ban", "payment system outage", "Visa outage", "Mastercard outage"],
            "thesis_90d": {
                "bearish": "Directa: una caída de Fedwire/Visa/Mastercard (ya pasó en 2018, 2019, 2021) congela liquidez interbancaria o comercio minorista por horas — el impacto en el precio de la acción es efímero (horas-días) pero el riesgo reputacional/regulatorio dura el trimestre.",
            },
            "companies": _companies(("V", "chokepoint"), ("MA", "chokepoint"), ("JPM", "indirect"), ("C", "indirect")),
        },
    ],
    "energy_oil_gas": [
        {
            "chokepoint": "Strait of Hormuz / Middle East oil disruption",
            "keywords": ["Strait of Hormuz", "Iran oil", "Middle East oil shock", "Gulf oil disruption"],
            "thesis_90d": {
                "bearish": "Directa: Delta/United/American/Southwest están 100% SIN cobertura de combustible desde 2025 — un shock de petróleo por Hormuz les pega dólar por dólar en margen dentro del mismo trimestre, sin colchón de hedge. Carnival tampoco tiene cobertura.",
                "bullish": "Dow/LyondellBasell (crackers de etano, gas barato de EE.UU. vs. nafta cara en Europa/Asia) amplían margen cuando sube el petróleo pero no el gas — y Scorpio/Frontline (tanqueros) se benefician de las tarifas de flete más altas por el desvío de rutas, aunque su re-rating de acción puede tardar semanas en alcanzar al spike de tarifas.",
            },
            "companies": _companies(
                ("DAL", "direct"), ("UAL", "direct"), ("AAL", "direct"), ("LUV", "direct"), ("CCL", "direct"), ("RCL", "indirect"),
                ("DOW", "beneficiary"), ("LYB", "beneficiary"), ("STNG", "beneficiary"), ("FRO", "beneficiary"),
                ("CF", "indirect"), ("NTR", "indirect"), ("VST", "indirect", "bullish"), ("NRG", "indirect", "bullish"), ("CEG", "beneficiary"),
            ),
        },
    ],
    "consumer_electronics": [
        {
            "chokepoint": "China manufacturing/tariff exposure (Foxconn assembly)",
            "keywords": ["Foxconn", "China manufacturing tariff", "Zhengzhou", "Apple China"],
            "thesis_90d": {
                "bearish": "Directa: un lockdown o disrupción en las plantas de Foxconn en China (ej. Zhengzhou 2022) retrasa producción de iPhone dentro del trimestre de lanzamiento — Apple está diversificando a India pero la mayoría de volumen sigue concentrado en China.",
            },
            "companies": _companies(("AAPL", "direct"), ("2317.TW", "chokepoint")),
        },
        {
            "chokepoint": "Memory/DRAM shortage (Samsung/SK Hynix/Micron)",
            "keywords": ["DRAM shortage", "memory shortage", "HBM shortage", "NAND price"],
            "thesis_90d": {
                "bearish": "Directa: la escasez de memoria ya está frenando pronósticos de envíos de smartphones para 2026 — pero para Micron/Samsung/SK Hynix MISMOS, la escasez es alcista de precio (más ingreso por unidad) aunque bajista de volumen para sus clientes finales (Apple, fabricantes chinos).",
            },
            "companies": _companies(("MU", "direct", "bullish"), ("005930.KS", "direct", "bullish"), ("000660.KS", "direct", "bullish")),
        },
    ],
    "shipping_logistics": [
        {
            "chokepoint": "Red Sea / Suez chokepoint disruption",
            "keywords": ["Red Sea attack", "Houthi", "Suez Canal", "Bab-el-Mandeb", "Cape of Good Hope reroute"],
            "thesis_90d": {
                "bearish": "Indirecta y con rezago conocido: Restoration Hardware perdió $40M de ingreso en un trimestre por retrasos del Mar Rojo; Steve Madden metió 20-25pb de golpe a margen — el patrón de rezago es 1-2 TRIMESTRES desde el evento hasta que aparece en el resultado de un retailer, así que hay ventana para posicionarse antes del próximo reporte trimestral tras un evento de disrupción.",
                "bullish": "Maersk/Hapag-Lloyd/ZIM se benefician de tarifas de flete más altas por el desvío obligado a Cabo de Buena Esperanza (menos barcos disponibles = más tarifa) — Maersk subió su guidance 4 veces en 2024 por esto. La reacción de la ACCIÓN del naviero es rápida (días-semanas), más rápida que la de los retailers afectados negativamente.",
            },
            "companies": _companies(
                ("MAERSK-B.CO", "chokepoint", "bullish"), ("HLAG.DE", "chokepoint", "bullish"), ("ZIM", "beneficiary"), ("1919.HK", "chokepoint", "bullish"),
                ("RH", "indirect"), ("SHOO", "indirect"), ("ADS.DE", "indirect"),
            ),
        },
        {
            "chokepoint": "Panama Canal drought / transit restrictions",
            "keywords": ["Panama Canal", "Gatun Lake", "canal drought", "canal transit restriction"],
            "thesis_90d": {
                "bullish": "Union Pacific/Norfolk Southern se benefician como ruta alternativa terrestre cuando el canal restringe tránsitos — un anuncio de restricción de calado es alcista para el volumen intermodal ferroviario dentro del mismo trimestre.",
            },
            "companies": _companies(("UNP", "beneficiary"), ("NSC", "beneficiary")),
        },
        {
            "chokepoint": "Global port congestion",
            "keywords": ["port congestion", "vessel wait time", "port dwell time", "container backlog"],
            "thesis_90d": {
                "bearish": "Indirecta: la congestión de puertos (ya en máximo de 4 años en 2026) se traslada a costos de flete/almacenaje para J.B. Hunt/Expeditors/C.H. Robinson dentro de 2-6 semanas — más lento que el mercado de fletes spot pero más rápido que el impacto en retailers.",
            },
            "companies": _companies(("JBHT", "indirect"), ("CHRW", "indirect"), ("EXPD", "indirect")),
        },
    ],
    "aerospace_defense": [
        {
            "chokepoint": "Titanium supply (Russia/VSMPO-AVISMA)",
            "keywords": ["titanium supply", "VSMPO", "Russia titanium", "titanium sanctions"],
            "thesis_90d": {
                "bearish": "Directa: Boeing ya suspendió compras de VSMPO en 2022 pero la dependencia no está totalmente resuelta (Airbus siguió comprando) — una escalada de sanciones o corte real de suministro ruso subiría costos de titanio dentro del trimestre para ambos fabricantes.",
                "bullish": "Howmet Aerospace, con capacidad de forjado/fundición occidental, gana poder de precio cada vez que se tensiona el suministro de titanio ruso.",
            },
            "companies": _companies(("BA", "direct"), ("HWM", "beneficiary")),
        },
        {
            "chokepoint": "Defense prime political/policy statements (contracts, buybacks, F-35 pricing)",
            "keywords": ["defense contractor", "F-35 cost", "defense budget", "Pentagon contract award", "government shutdown defense"],
            "thesis_90d": {
                "bearish": "Directa: un solo tweet/declaración presidencial sobre costos de un programa (ej. LMT -4-5% en dic-2016 por el F-35) mueve el precio el MISMO DÍA — es la tesis de materialización más rápida de todo el registro, literalmente horas, no 90 días. La orden ejecutiva de ene-2026 sobre buybacks causó una caída conjunta de BA/RTX/GD/LMT/NOC revertida el mismo día por un anuncio de presupuesto — la volatilidad intradía es la norma, no la excepción, en este chokepoint.",
            },
            "companies": _companies(("LMT", "direct"), ("BA", "direct"), ("RTX", "direct"), ("NOC", "direct"), ("GD", "direct")),
        },
        {
            "chokepoint": "Jet engine issues (Pratt & Whitney GTF, GE, Rolls-Royce)",
            "keywords": ["GTF engine", "Pratt Whitney recall", "jet engine groundings", "turbine disk"],
            "thesis_90d": {
                "bearish": "Directa: el recall de motores GTF de RTX (2023, todavía coleando en 2026) es un caso de daño que se sigue materializando trimestre a trimestre — cada actualización de alcance de la inspección es un evento de guidance revisable dentro de la ventana de 90 días.",
                "bullish": "GE Aerospace (motores de banda ancha, sin el problema del GTF) gana cuota de mercado relativa cada vez que RTX reporta una extensión del problema.",
            },
            "companies": _companies(("RTX", "direct"), ("GE", "beneficiary")),
        },
    ],
}


def all_keywords():
    """Flat list of (industry, chokepoint, keyword) for building a matcher."""
    rows = []
    for industry, entries in REGISTRY.items():
        for entry in entries:
            for kw in entry["keywords"]:
                rows.append((industry, entry["chokepoint"], kw))
    return rows


def companies_for(industry: str, chokepoint: str) -> list[dict]:
    for entry in REGISTRY.get(industry, []):
        if entry["chokepoint"] == chokepoint:
            return entry["companies"]
    return []


def thesis_for(industry: str, chokepoint: str) -> dict:
    for entry in REGISTRY.get(industry, []):
        if entry["chokepoint"] == chokepoint:
            return entry.get("thesis_90d", {})
    return {}
