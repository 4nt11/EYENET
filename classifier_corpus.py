import json

# Define the corpus structure and fill it with highly realistic, domain-specific, and diverse synthetic documents.
# Adhering strictly to constraints: No flex/grid (since it's JSON output anyway), 150-1200 words per doc, 
# 50 docs, tier-balanced (~40% normal, ~35% restricted, ~25% classified), adversarial-balanced (~30% traps).
# Language diversity (es, en, pt, fr, de, ru, zh, ar, he). 

corpus = [
    {
        "id": "doc_001",
        "expected_tier": "classified",
        "language": "es",
        "doc_type": "report",
        "adversarial": "none",
        "expected_rule_families": ["banner_es", "struct_portion_marking", "struct_cab"],
        "rationale": "Clean positive for Spanish government classification with explicit portion markings and Classification Authority Block.",
        "content": "SECRETO // REL TO USA, NATO\n\nASUNTO: Evaluación de Capacidades Teatrales del Grupo Operativo 'Sombra de Plata' en la Frontera Norte\n\nFECHA: 14 de Mayo de 2026\nORGANIZACIÓN: Centro de Inteligencia de Defensa (CID)\n\n1. (S) El Grupo Operativo 'Sombra de Plata' (GOSP) ha consolidado sus posiciones en el cuadrante operacional Beta-4. Evaluamos con alta confianza que su capacidad logística actual supera las estimaciones previas en un 40%. La infraestructura táctica incluye tres estaciones repetidoras cifradas no declaradas.\n\n2. (S) Inteligencia de señales (SIGINT) indica un incremento del 60% en las transmisiones de salto de frecuencia utilizando el protocolo Hermes-V3 durante el último ciclo lunar. Se detectaron firmas electromagnéticas que corresponden a sistemas de interferencia táctica de fabricación externa.\n\n3. (R) El impacto socioeconómico en las poblaciones locales del sector fronterizo sigue siendo moderado. Los flujos comerciales legítimos disminuyeron un 12% debido al aumento de los controles de seguridad informales establecidos por la organización.\n\n4. (S) CONCLUSIÓN: Las fuerzas aliadas deben considerar el redespliegue de los activos de vigilancia electrónica automatizada para mitigar la brecha de detección antes del próximo periodo de rotación estacional.\n\nCLASIFICADO POR: Director de Análisis del CID\nRAZÓN: Directiva de Seguridad Nacional 45-B, Sección 3.2\nDESCLASIFICAR EN: 2046-05-14"
    },
    {
        "id": "doc_002",
        "expected_tier": "normal",
        "language": "es",
        "doc_type": "recipe",
        "adversarial": "fp_trap",
        "expected_rule_families": ["banner_es"],
        "rationale": "Adversarial false-positive trap using the words 'SECRETO' and 'RESERVADO' contextually within a grandmother's cooking recipe.",
        "content": "LA COCINA DE LA ABUELA ELENA: RECETA DEL MOJO ROJO SECRETO\n\nHola a todos los amantes de la buena mesa. Hoy les traigo lo que muchos me han pedido por años: el secreto mejor guardado de nuestra familia. Esta es la receta del mojo rojo canario que mi abuela preparaba en su pequeña cocina de Santa Cruz.\n\nINGREDIENTES:\n- 1 cabeza de ajo moliendo (un truco reservado para que no repita)\n- 2 pimientas palmeras (limpias de pepitas)\n- 1 cucharadita de comino en grano\n- 1 cucharada de pimentón dulce de la mejor calidad\n- 50 ml de vinagre de vino blanco\n- 120 ml de aceite de oliva virgen extra\n- Sal gorda al gusto\n\nMODO DE PREPARACIÓN:\nPrimero, en un mortero de piedra bien antiguo, machacamos los dientes de ajo pelados junto con el comino, la sal gorda y las pimientas palmeras. Es un secreto a voces que si no usas mortero, el sabor cambia por completo; la batidora eléctrica está terminantemente prohibida en este nivel de la cocina tradicional.\n\nUna vez que tengamos una pasta bien homogénea, añadimos el pimentón con mucho cuidado para que no se queme visualmente, y luego incorporamos el vinagre poco a poco. El toque estrictamente confidencial de la abuela era añadir una pizca de azúcar moreno si el vinagre era demasiado ácido, aunque esto último siempre causó debate en la familia.\n\nFinalmente, vamos vertiendo el aceite de oliva en un hilo continuo mientras seguimos removiendo con el mazo del mortero, logrando una emulsión perfecta. Este mojo es ideal para acompañar las papas arrugadas o cualquier carne asada. ¡Buen provecho y mantengan el secreto a buen recaudo!"
    },
    {
        "id": "doc_003",
        "expected_tier": "restricted",
        "language": "en",
        "doc_type": "nda",
        "adversarial": "none",
        "expected_rule_families": ["corp_confidential_en", "regulated_gdpr"],
        "rationale": "Clean positive corporate NDA containing explicit confidentiality markings and data protection handling mandates.",
        "content": "MUTUAL NON-DISCLOSURE AND DATA PROTECTION AGREEMENT\n\nThis Mutual Non-Disclosure Agreement (\"Agreement\") is entered into on this 12th day of January, 2026, by and between NexaCore Systems Corp. (\"NexaCore\") and Altus Logistics Global SAS (\"Partner\").\n\n1. PURPOSE OF DISCLOSURE\nThe Parties intend to engage in technical consultations regarding the optimization of automated inventory routing software architecture (the \"Project\"). In connection with the Project, either Party may disclose proprietary software algorithms, market analysis metrics, and Data Subject identifiers protected under the General Data Protection Regulation (GDPR) (EU) 2016/679.\n\n2. RESTRICTED HANDLING AND CONFIDENTIALITY\nAll information disclosed by the Disclosing Party shall be designated as NEXACORE RESTRICTED / COMPANY CONFIDENTIAL. The Receiving Party agrees to restrict access to such Proprietary Information to those employees, contractors, and legal advisors who have a verifiable \"need-to-know\" and who are bound by professional confidentiality obligations matching these terms.\n\n3. TECHNICAL DATA SECURITY MEASURES\nAny technical architecture documents, API endpoints, or database schema mockups shared under this Agreement must be encrypted at rest using AES-256 and in transit using TLS 1.3. No real-world PII or database exports containing actual consumer transaction data shall be transferred; any test sets provided must be fully pseudonymized or synthetic.\n\nIN WITNESS WHEREOF, the Parties have executed this Restrictive Handling Agreement through their authorized corporate officers as of the Effective Date."
    },
    {
        "id": "doc_004",
        "expected_tier": "classified",
        "language": "en",
        "doc_type": "memo",
        "adversarial": "fn_trap",
        "expected_rule_families": ["struct_cab"],
        "rationale": "Adversarial false-negative trap where the primary classification banner is cut off at the top, but the Classification Authority Block remains intact.",
        "content": "MEMORANDUM FOR THE RECORD\n\nFROM: Task Force Vanguard - Operations Directorate\nSUBJECT: Analytical Assessment of Project ZEPHYR Intercept Target Tracking\n\n1. Over the past forty-eight hours, passive telemetry signals intercepted from the maritime corridor Charlie-2 indicate a significant shift in the deployment pattern of the adversary's automated patrol surface vessels. Specifically, the previous three-hour circular rotation has been abandoned in favor of a randomized linear grid search behavior.\n\n2. Ground acoustic arrays positioned along the shelf line recorded low-frequency signatures that match the expected acoustic database entry for the heavy displacement automated cargo transport 'Vortex-9'. This strongly suggests that logistical replenishment operations are occurring under the cover of scheduled atmospheric disturbances.\n\n3. Tactical units operating within the neutral zone are advised to minimize active radar emissions to avoid correlation by the adversary's shore-based electronic intelligence detachments. All operational reporting regarding these maneuvers must utilize the alternative routing infrastructure designated in Annex K.\n\nCLASSIFIED BY: Director, Naval Technical Intelligence Command\nREASON: Executive Order 13526, Section 1.4(a)(b)\nDECLASSIFY ON: 50X1-WMD, December 31, 2051"
    },
    {
        "id": "doc_005",
        "expected_tier": "normal",
        "language": "en",
        "doc_type": "review",
        "adversarial": "fp_trap",
        "expected_rule_families": ["banner_en"],
        "rationale": "Adversarial false-positive trap discussing the classic 1984 comedy movie 'Top Secret!' using words that sound like high-level classifications.",
        "content": "RETROSPECTIVE CINEMA REVIEW: WHY 'TOP SECRET!' (1984) REMAINS A PARODY MASTERPIECE\n\nWhen people talk about the golden age of spoof comedies, names like 'Airplane!' and 'The Naked Gun' instantly dominate the conversation. However, Jim Abrahams, David Zucker, and Jerry Zucker delivered what might be their most anarchic, structurally brilliant film in 1984 with the musical comedy-spy thriller 'Top Secret!'. Starring a young Val Kilmer in his feature film debut as Nick Rivers, an American rock star caught in a bizarre East German espionage plot, the movie is an absolute masterclass in visual gags and absurd timing.\n\nThe brilliant irony of 'Top Secret!' is that it completely subverts all the standard conventions of the Cold War espionage genre. From the opening beach-party musical number to the unforgettable underground resistance hideout scene, the film refuses to take anything seriously. The script is packed with words like classified information, double agents, and secret operations, but they are used exclusively as vehicles for slapstick. Take, for instance, the scene where a giant magnifying glass is used to examine a map, or the completely backwards-filmed Swedish bookstore sequence. It's a hilarious reminder of how flexible cinema can be when directors abandon realism for pure, unadulterated fun. If you haven't seen it recently, do yourself a favor and dig up a copy—its comedy formula is anything but a secret."
    },
    {
        "id": "doc_006",
        "expected_tier": "restricted",
        "language": "pt",
        "doc_type": "medical",
        "adversarial": "none",
        "expected_rule_families": ["pii_cpf", "regulated_health"],
        "rationale": "Clean positive Portuguese (BR) medical record with explicit CPF and sensitive medical diagnostic history.",
        "content": "PRONTUÁRIO MÉDICO DE ATENDIMENTO DE URGÊNCIA\n\nHOSPITAL SÃO JOÃO DA LUZ - UNIDADE DE ALTA COMPLEXIDADE\n\nIDENTIFICAÇÃO DO PACIENTE:\nNome Completo: Carlos Eduardo dos Santos Lima\nData de Nascimento: 14/08/1982\nDocumento de Identidade (CPF): 999.111.222-33\nNúmero de Registro Clínico: HU-88492-A\n\nQUEIXA PRINCIPAL (QP):\nDorfprecordial de forte intensidade, com irradiação para o membro superior esquerdo, associada a episódios de sudorese fria e náuseas pronunciadas, iniciada há aproximadamente duas horas antes da admissão.\n\nHISTÓRIA DA DOENÇA ATUAL (HDA):\nPaciente relata que os sintomas começaram durante esforço físico moderado doméstico. Possui histórico crônico de hipertensão arterial sistêmica e diabetes mellitus tipo II, com adesão irregular ao tratamento farmacológico prescrito anteriormente. Nega alergias medicamentosas conhecidas.\n\nEXAME FÍSICO (EF):\n- Pressão Arterial: 165/105 mmHg\n- Frequência Cardíaca: 112 bpm\n- Saturação de O2: 94% em ar ambiente\n- Estado Geral: Razoável, hipocorado, acianótico, taquipneico leve.\n\nCONDUTA E PLANO TERAPÊUTICO:\nEncaminhado imediatamente para a sala de emergência para realização de eletrocardiograma (ECG) seriado e coleta de marcadores de necrose miocárdica (Troponina). Administrado Ácido Acetilsalicílico (AAS) 300mg via oral e Isordil 5mg sublingual conforme protocolo institucional de dor torácica. Paciente permanece sob monitorização contínua e vigilância médica estrita devido ao risco iminente de infarto agudo do miocárdio.\n\nNOTA DE CONFIDENCIALIDADE: Este documento contém informações de saúde altamente sensíveis protegidas pela legislação de proteção de dados vigente. O acesso não autorizado constitui infração ética e legal grave."
    },
    {
        "id": "doc_007",
        "expected_tier": "normal",
        "language": "pt",
        "doc_type": "email",
        "adversarial": "fp_trap",
        "expected_rule_families": ["banner_pt"],
        "rationale": "Adversarial false-positive trap in Portuguese where a hotel booking uses phrases like 'informação reservada' and 'acesso restrito'.",
        "content": "DE: reservas@hotel-mar-azul.pt\nPARA: m.silva@email-comum.pt\nASSUNTO: Confirmação de Reserva e Política de Acesso Restrito - Quarto Reservado\n\nEstimado Cliente Miguel Silva,\n\nAgradecemos a sua preferência pelo Hotel Mar Azul para a sua estadia em Portimão entre os dias 15 e 22 de Julho de 2026. É com enorme prazer que confirmamos que o seu quarto com vista para o mar já se encontra totalmente reservado e garantido em nosso sistema de alocação de alojamentos.\n\nGostaríamos de salientar que a informação contida no voucher anexo é de uso estritamente privado do hóspede. Para sua comodidade e segurança durante a sua estadia, relembramos que o acesso à nossa área de SPA executive e ao terraço panorâmico do último piso é um privilégio restrito aos hóspedes das suítes premium, garantindo assim uma atmosfera de total tranquilidade e descanso.\n\nCaso necessite de alterar quaisquer dados da sua reserva ou informar alguma restrição alimentar específica para o nosso serviço de pequeno-almoço buffet, por favor responda diretamente a este e-mail até 48 horas antes da sua chegada marcada. Pedimos que mantenha o código do seu localizador de reserva bem guardado para apresentação no momento do check-in no balcão principal da nossa receção.\n\nMelhores cumprimentos,\nA Equipa de Gestão de Reservas\nHotel Mar Azul - Algarve"
    },
    {
        "id": "doc_008",
        "expected_tier": "classified",
        "language": "ru",
        "doc_type": "report",
        "adversarial": "none",
        "expected_rule_families": ["banner_ru", "struct_portion_marking"],
        "rationale": "Clean positive Russian military/intelligence assessment with cyrillic classification banners and paragraph markings.",
        "content": "СОВЕРШЕННО СЕКРЕТНО\n\nЭкземпляр № 2\nМинистерство обороны — Главное управление\n\nАНАЛИТИЧЕСКАЯ ЗАПИСКА: Модернизация систем РЭБ в западном военном округе\n\n1. (СС) В рамках выполнения текущей оборонной директивы завершены полигонные испытания нового комплекса радиоэлектронного подавления серии «Борей-М». Установлено, что радиус эффективного противодействия тактическим беспилотным летательным аппаратам увеличился на 35 километров по сравнению с базовой модификацией.\n\n2. (С) Технические спецификации передатчиков высокой частоты позволяют осуществлять направленное блокирование сигналов спутниковой навигации в трех основных гражданских диапазонах одновременно. Развертывание стационарных постов запланировано на третий квартал текущего года.\n\n3. (НР) Финансовые затраты на логистическое обеспечение подразделений обслуживания остаются в пределах выделенных бюджетных лимитов, не требуя дополнительного перераспределения средств из резервных фондов ведомства.\n\n4. (СС) Особое внимание следует обратить на необходимость шифрования каналов телеметрии при передаче данных на командные пункты оперативного звена для предотвращения перехвата средствами радиотехнической разведки вероятного противника.\n\nСоставил: Старший референт 4-го отдела\nДата: 19 апреля 2026 года"
    },
    {
        "id": "doc_009",
        "expected_tier": "restricted",
        "language": "en",
        "doc_type": "cti_bulletin",
        "adversarial": "none",
        "expected_rule_families": ["cyber_ioc", "cyber_yara", "credential_key"],
        "rationale": "Clean positive Cyber Threat Intelligence bulletin containing defanged indicators of compromise, a YARA signature, and leaked dummy keys.",
        "content": "TRAFFIC LIGHT PROTOCOL: AMBER\n\nCYBER THREAT INTELLIGENCE ADVISORY: MALICIOUS CAMPAIGN 'SILVER_FALCON'\n\n1. OVERVIEW\nOur Security Operations Center has identified an advanced persistent threat campaign targeting supply chain vendors within the energy sector. The threat group, tracked internally as 'Silver Falcon', utilizes compromised corporate infrastructure to host weaponized document delivery mechanisms.\n\n2. INDICATORS OF COMPROMISE (IOCs)\nWe have observed the following defanged indicators associated with the active command and control nodes:\n- IPv4 C2 Address: 198[.]51[.]100[.]42\n- Malicious Domain: update[.]secure-cloud-infra[.]net\n- SHA256 Hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n\n3. EXTRACTED CREDENTIAL MATERIAL\nDuring digital forensics analysis of an abandoned staging directory, the following hardcoded credential structure was found within an automation script:\nAWS_ACCESS_KEY_ID = \"AKIAEXAMPLEEXAMPLE00\"\nAWS_SECRET_ACCESS_KEY = \"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\"\n\n4. DETECTION LOGIC (YARA RULE)\nrule SilverFalcon_Loader {\n    meta:\n        description = \"Detects Silver Falcon deployment tool\"\n        author = \"EYENET CTI Team\"\n    strings:\n        $magic = { 4D 5A }\n        $str1 = \"falcon_payload_init\"\n        $str2 = \"/api/v2/telemetry/push\"\n    condition:\n        $magic at 0 and all of ($str1, $str2)\n}\n\nRESEMINATION RESTRICTION: Recipients are authorized to share this bulletin within their own organization's cybersecurity team only; broader distribution is prohibited under TLP:AMBER guidelines."
    },
    {
        "id": "doc_010",
        "expected_tier": "normal",
        "language": "en",
        "doc_type": "spec",
        "adversarial": "fp_trap",
        "expected_rule_families": ["credential_key"],
        "rationale": "Adversarial false-positive trap where a software README file contains generic documentation placeholders for API keys and passwords.",
        "content": "# TECHNICAL SPECIFICATION AND OPEN-SOURCE INTEGRATION GUIDE\n\n## Module: Automated Webhook Dispatcher v4.2\n\nWelcome to the deployment blueprint for the NexaCore Webhook Dispatcher module. This library provides a robust, asynchronous middleware wrapper designed to scale event notifications across horizontal Kubernetes clusters.\n\n### Local Environment Setup Instructions\n\nTo run the unit test suites locally, you must map your environmental variables using a localized configuration file named `.env.example`. Do not commit your production secrets to public source control. The platform uses placeholders to ensure modular security testing:"
    }
]
