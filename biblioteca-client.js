/** Public catalog client. No GitHub token needed. Import as an ES module. */
export async function carregarBiblioteca(catalogoURL) {
  const url = new URL(catalogoURL);
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Catálogo indisponível (${response.status}).`);
  const catalog = await response.json();
  if (catalog.schema_version !== 1 || !Array.isArray(catalog.models)) {
    throw new Error('Formato de catálogo incompatível.');
  }
  return catalog.models.map(model => {
    if (!/^modelos\/[a-z0-9-]+\.glb$/.test(model.file) ||
        !/^[a-f0-9]{64}$/.test(model.sha256) ||
        !Number.isSafeInteger(model.bytes) || model.bytes < 20) {
      throw new Error('Entrada inválida no catálogo.');
    }
    return { ...model, url: new URL(model.file, url).href };
  });
}

export async function baixarModelo(model, { signal, maxBytes = 20 * 1024 * 1024 } = {}) {
  if (model.bytes > maxBytes) throw new Error('Modelo excede o limite de download.');
  const response = await fetch(model.url, { signal, cache: 'no-cache' });
  if (!response.ok) throw new Error(`Falha no download (${response.status}).`);
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > maxBytes || size > model.bytes) {
        await reader.cancel();
        throw new Error('Arquivo recebido excede o tamanho esperado.');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  if (size !== model.bytes) throw new Error('Arquivo incompleto ou catálogo em atualização.');
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  const hex = Array.from(hash, n => n.toString(16).padStart(2, '0')).join('');
  if (hex !== model.sha256) throw new Error('Biblioteca em atualização: atualize o catálogo e tente novamente.');
  return bytes.buffer; // Pass to the game's GLB importer.
}
