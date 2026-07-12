
SUPPORTED_LANGUAGES = {
    'en': 'English',
    'de': 'Deutsch',
    'pt': 'Português',
}
SUPPORTED_PROFICIENCIES = {
    'beginner': {'label': {'en': 'Beginner', 'de': 'Anfänger', 'pt': 'Iniciante'}},
    'rookie': {'label': {'en': 'Rookie', 'de': 'Rookie', 'pt': 'Novato'}},
    'intermediate': {'label': {'en': 'Intermediate', 'de': 'Fortgeschritten', 'pt': 'Intermédio'}},
    'advanced': {'label': {'en': 'Advanced', 'de': 'Advanced', 'pt': 'Avançado'}},
    'pro': {'label': {'en': 'Pro', 'de': 'Pro', 'pt': 'Pro'}},
}
DEFAULT_LANGUAGE = 'en'
DEFAULT_PROFICIENCY = 'advanced'
TRANSLATIONS = {
 'en': {
  'app_tagline':'Check the swell, pick the peak, stay stoked.', 'username':'Username','password':'Password','login_button':'Paddle in','invalid_credentials':'Invalid username or password.',
  'logout':'Hang loose logout','back_to_lineup':'Back to lineup','date_tz':'Europe/Lisbon','daily_lineup_call':'Daily lineup call','best_spot':'Best surf spot of the day',
  'best_intro':'Scoring for the selected surfer level across morning take-off, midday set, and evening glass-off. Confidence is about data quality — not stoke.',
  'morning':'Morning','midday':'Midday','evening':'Evening','session':'session','surf_call':'Surf call','estimated_breaking':'Estimated breaking-wave range','swell':'Swell','wind':'Wind','tide':'Tide','water_temp':'Water temperature','newest_data':'Newest source data','inspect_peak':'Inspect this peak','no_recommendation':'No recommendation available.',
  'alternatives_title':'2nd and 3rd best alternatives','alternatives_intro':'Backup peaks for the same time window and proficiency setting.', 'second_best':'2nd best','third_best':'3rd best','no_alternative':'No alternative available.',
  'provider_lineup':'Data provider lineup','provider_status':'Provider Status','provider_intro':'Each provider is protected by a 30-minute data-gathering bundle limit. Hover for the health reason; click for the human-readable data payload.',
  'spot_catalog':'Spot catalog','surf_spots':'Surf spots','spots_intro':'All known Aljezur-area breaks in the prototype: beach breaks, river mouths, reef/rock setups, and observation-only advanced spots.',
  'name':'Name','zone':'Zone','type':'Type','difficulty':'Difficulty','current_summary':'Current lineup summary','confidence':'Confidence','detail':'Detail','watch_set':'watch the set before drop-in','observation_only':'Observation-only / not scored — inspect before paddling out',
  'language':'Language','proficiency':'Difficulty preference','save_preferences':'Set','close':'Close','why_status':'Why this status?','last_bundle':'Last data bundle','rate_limit':'Rate limit','human_data':'Human-readable data fetched',
  'peak_notes':'Peak notes','spot_check':'spot check','zone_section':'Zone or section','beach_name':'Beach name','latitude':'Latitude','longitude':'Longitude','map':'Map','maps_coordinates':'Google Maps coordinates','description':'Description','multiple_zones':'Multiple zones / peaks','suitable_level':'Suitable surfer level','preferred_swell_dirs':'Preferred swell directions','preferred_period':'Preferred swell period range','preferred_wind_dirs':'Preferred wind directions','relevant_tide':'Relevant tide range','hazards':'Known hazards','access_notes':'Access notes','sources_used':'Sources used','last_update':'Last update time','session_scores':'Session scores','current_forecast':'Current forecast summary','no_score':'No score for this daypart.',
  'classification_excellent':'excellent','classification_good':'good','classification_workable':'workable','classification_poor':'poor','call_go':'Go','call_maybe':'Maybe','call_wait':'Wait','call_no':'No-go',
 },
 'de': {
  'app_tagline':'Check den Swell, wähle den Peak, bleib stoked.', 'username':'Benutzername','password':'Passwort','login_button':'Reinpaddeln','invalid_credentials':'Benutzername oder Passwort ungültig.',
  'logout':'Hang-loose Logout','back_to_lineup':'Zurück zum Lineup','date_tz':'Europa/Lissabon','daily_lineup_call':'Täglicher Lineup-Call','best_spot':'Surfspot des Tages',
  'best_intro':'Scoring für dein gewähltes Surf-Level für Morning Take-off, Midday Set und Evening Glass-off. Confidence beschreibt Datenqualität — nicht Stoke.',
  'morning':'Morgens','midday':'Mittags','evening':'Abends','session':'Session','surf_call':'Surf Call','estimated_breaking':'Geschätzte brechende Wellenhöhe','swell':'Swell','wind':'Wind','tide':'Tide','water_temp':'Wasser\u00adtemperatur','newest_data':'Neueste Quelldaten','inspect_peak':'Peak ansehen','no_recommendation':'Keine Empfehlung verfügbar.',
  'alternatives_title':'Zweit- und drittbeste Alternativen','alternatives_intro':'Backup-Peaks für dasselbe Zeitfenster und Surf-Level.', 'second_best':'2. Wahl','third_best':'3. Wahl','no_alternative':'Keine Alternative verfügbar.',
  'provider_lineup':'Data-Provider-Lineup','provider_status':'Provider Status','provider_intro':'Jeder Provider ist durch ein 30-Minuten-Datenbeschaffungs-Bundle-Limit geschützt. Mouse-over zeigt den Health-Grund; Klick zeigt die human-readable Daten.',
  'spot_catalog':'Spot-Katalog','surf_spots':'Surfspots','spots_intro':'Alle bekannten Breaks rund um Aljezur im Prototyp: Beachbreaks, Rivermouths, Reef-/Rock-Setups und Advanced-only Observation-Spots.',
  'name':'Name','zone':'Zone','type':'Typ','difficulty':'Schwierigkeit','current_summary':'Aktuelle Lineup-Zusammenfassung','confidence':'Confidence','detail':'Details','watch_set':'Set beobachten vor dem Drop-in','observation_only':'Nur Beobachtung / nicht gescored — vor dem Paddeln prüfen',
  'language':'Sprache','proficiency':'Schwierigkeitspräferenz','save_preferences':'Setzen','close':'Schließen','why_status':'Warum dieser Status?','last_bundle':'Letztes Daten-Bundle','rate_limit':'Rate Limit','human_data':'Abgerufene Daten in lesbarer Form',
  'peak_notes':'Peak-Notizen','spot_check':'Spot-Check','zone_section':'Zone oder Abschnitt','beach_name':'Beach-Name','latitude':'Breitengrad','longitude':'Längengrad','map':'Karte','maps_coordinates':'Google-Maps-Koordinaten','description':'Beschreibung','multiple_zones':'Mehrere Zonen / Peaks','suitable_level':'Geeignetes Surf-Level','preferred_swell_dirs':'Bevorzugte Swell-Richtungen','preferred_period':'Bevorzugter Periodenbereich','preferred_wind_dirs':'Bevorzugte Windrichtungen','relevant_tide':'Relevanter Tide-Bereich','hazards':'Bekannte Gefahren','access_notes':'Zugangshinweise','sources_used':'Genutzte Quellen','last_update':'Letzte Aktualisierung','session_scores':'Session-Scores','current_forecast':'Aktuelle Forecast-Zusammenfassung','no_score':'Kein Score für dieses Tagesfenster.',
  'classification_excellent':'exzellent','classification_good':'gut','classification_workable':'machbar','classification_poor':'schwach','call_go':'Go','call_maybe':'Vielleicht','call_wait':'Warten','call_no':'No-go',
 },
 'pt': {
  'app_tagline':'Vê o swell, escolhe o pico, fica stoked.', 'username':'Utilizador','password':'Palavra-passe','login_button':'Entrar no lineup','invalid_credentials':'Utilizador ou palavra-passe inválidos.',
  'logout':'Sair hang loose','back_to_lineup':'Voltar ao lineup','date_tz':'Europa/Lisboa','daily_lineup_call':'Chamada diária do lineup','best_spot':'Melhor surf spot do dia',
  'best_intro':'Pontuação para o nível escolhido nas sessões de manhã, meio-dia e fim de tarde. A confiança mede a qualidade dos dados — não o stoke.',
  'morning':'Manhã','midday':'Meio-dia','evening':'Fim de tarde','session':'sessão','surf_call':'Surf call','estimated_breaking':'Intervalo estimado da onda a rebentar','swell':'Swell','wind':'Vento','tide':'Maré','water_temp':'Temperatura da água','newest_data':'Dados de origem mais recentes','inspect_peak':'Ver este pico','no_recommendation':'Sem recomendação disponível.',
  'alternatives_title':'2.ª e 3.ª melhores alternativas','alternatives_intro':'Picos de reserva para a mesma janela e nível.', 'second_best':'2.ª melhor','third_best':'3.ª melhor','no_alternative':'Sem alternativa disponível.',
  'provider_lineup':'Lineup dos fornecedores de dados','provider_status':'Estado dos fornecedores','provider_intro':'Cada fornecedor está protegido por um limite de um pacote de recolha a cada 30 minutos. Passa o rato para ver o motivo; clica para ver dados legíveis.',
  'spot_catalog':'Catálogo de spots','surf_spots':'Surf spots','spots_intro':'Todos os breaks conhecidos na zona de Aljezur no protótipo: beach breaks, fozes de rio, reef/rock setups e spots só para observação avançada.',
  'name':'Nome','zone':'Zona','type':'Tipo','difficulty':'Dificuldade','current_summary':'Resumo atual do lineup','confidence':'Confiança','detail':'Detalhe','watch_set':'observa o set antes do drop-in','observation_only':'Só observação / sem pontuação — verifica antes de remar',
  'language':'Idioma','proficiency':'Preferência de dificuldade','save_preferences':'Aplicar','close':'Fechar','why_status':'Porquê este estado?','last_bundle':'Último pacote de dados','rate_limit':'Limite de frequência','human_data':'Dados recolhidos em forma legível',
  'peak_notes':'Notas do pico','spot_check':'spot check','zone_section':'Zona ou secção','beach_name':'Nome da praia','latitude':'Latitude','longitude':'Longitude','map':'Mapa','maps_coordinates':'Coordenadas Google Maps','description':'Descrição','multiple_zones':'Várias zonas / picos','suitable_level':'Nível adequado','preferred_swell_dirs':'Direções de swell preferidas','preferred_period':'Intervalo de período preferido','preferred_wind_dirs':'Direções de vento preferidas','relevant_tide':'Intervalo de maré relevante','hazards':'Perigos conhecidos','access_notes':'Notas de acesso','sources_used':'Fontes usadas','last_update':'Última atualização','session_scores':'Pontuações por sessão','current_forecast':'Resumo atual da previsão','no_score':'Sem pontuação para esta parte do dia.',
  'classification_excellent':'excelente','classification_good':'bom','classification_workable':'possível','classification_poor':'fraco','call_go':'Vai','call_maybe':'Talvez','call_wait':'Espera','call_no':'No-go',
 },
}
def normalize_language(lang):
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
def normalize_proficiency(value):
    return value if value in SUPPORTED_PROFICIENCIES else DEFAULT_PROFICIENCY
def translate(lang, key):
    lang = normalize_language(lang)
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, TRANSLATIONS['en'].get(key, key))
def label_for_proficiency(proficiency, lang):
    proficiency = normalize_proficiency(proficiency); lang = normalize_language(lang)
    return SUPPORTED_PROFICIENCIES[proficiency]['label'].get(lang, SUPPORTED_PROFICIENCIES[proficiency]['label']['en'])
def surf_call(score, confidence, lang):
    t=lambda k: translate(lang,k)
    if confidence == 'Uncertain' and score < 65: return t('call_wait')
    if score >= 70: return t('call_go')
    if score >= 52: return t('call_maybe')
    if score >= 38: return t('call_wait')
    return t('call_no')
def classification_label(value, lang):
    return translate(lang, 'classification_'+str(value))
