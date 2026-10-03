import { getHealth } from "./api.js";
import { initializeChat } from "./chat.js";
import {
  initializeDocumentsUI,
  loadDocuments,
  loadTaxonomy,
} from "./documents.js";


async function bootstrap() {
  initializeDocumentsUI();
  initializeChat();

  try {
    await getHealth();
  } catch (error) {
    console.error("Backend health check failed", error);
  }

  try {
    await loadTaxonomy();
  } catch (error) {
    console.error("Taxonomy load failed", error);
  }

  await loadDocuments();
}


bootstrap();
