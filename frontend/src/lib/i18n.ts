import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import fr from "@/i18n/fr.json";
import en from "@/i18n/en.json";

void i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: "fr",
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export default i18n;
