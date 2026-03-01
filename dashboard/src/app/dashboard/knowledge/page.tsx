'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function KnowledgePage() {
  const [docs, setDocs] = useState<Array<Record<string, unknown>>>([])
  const [showUpload, setShowUpload] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<Record<string, unknown>>>([])
  const [uploading, setUploading] = useState(false)

  useEffect(() => { loadDocs() }, [])

  async function loadDocs() {
    try {
      const data = await api.listDocuments()
      setDocs(data)
    } catch (err) {
      console.error(err)
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    setUploading(true)
    try {
      await api.uploadDocument({ title, content })
      setTitle('')
      setContent('')
      setShowUpload(false)
      loadDocs()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this document?')) return
    await api.deleteDocument(id)
    loadDocs()
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return
    try {
      const results = await api.searchKnowledge(searchQuery)
      setSearchResults(results)
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Knowledge Base</h1>
        <button onClick={() => setShowUpload(!showUpload)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          {showUpload ? 'Cancel' : '+ Add Document'}
        </button>
      </div>

      {/* Semantic Search */}
      <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
        <h3 className="font-semibold text-gray-700 mb-3">Search Knowledge Base</h3>
        <div className="flex gap-2">
          <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
            placeholder="Ask a question to test retrieval..."
            className="flex-1 px-3 py-2 border rounded-lg text-sm" />
          <button onClick={handleSearch}
            className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900">Search</button>
        </div>
        {searchResults.length > 0 && (
          <div className="mt-3 space-y-2">
            {searchResults.map((r, i) => (
              <div key={i} className="p-3 bg-gray-50 rounded-lg text-sm">
                <div className="flex justify-between mb-1">
                  <span className="font-medium">{String(r.title)}</span>
                  <span className="text-gray-400">Score: {Number(r.score).toFixed(3)}</span>
                </div>
                <p className="text-gray-600 text-xs">{String(r.content).slice(0, 200)}...</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Upload Form */}
      {showUpload && (
        <form onSubmit={handleUpload} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">Upload Document</h3>
          <input value={title} onChange={e => setTitle(e.target.value)}
            placeholder="Document title (e.g., Room Types & Pricing)"
            className="w-full px-3 py-2 border rounded-lg text-sm mb-3" required />
          <textarea value={content} onChange={e => setContent(e.target.value)}
            placeholder="Paste document content here. It will be automatically chunked and embedded for semantic search."
            className="w-full px-3 py-2 border rounded-lg text-sm" rows={10} required />
          <button type="submit" disabled={uploading}
            className="mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            {uploading ? 'Processing...' : 'Upload & Embed'}
          </button>
        </form>
      )}

      {/* Document List */}
      <div className="space-y-3">
        {docs.map(doc => (
          <div key={String(doc.id)} className="p-4 bg-white rounded-xl shadow-sm border flex justify-between items-center">
            <div>
              <h4 className="font-medium text-gray-800">{String(doc.title)}</h4>
              <p className="text-xs text-gray-400 mt-1">
                {String(doc.chunk_count)} chunks | Added {new Date(String(doc.created_at)).toLocaleDateString()}
              </p>
            </div>
            <button onClick={() => handleDelete(String(doc.id))}
              className="text-red-400 hover:text-red-600 text-sm">Delete</button>
          </div>
        ))}
        {docs.length === 0 && (
          <p className="text-gray-500 text-center py-8">
            No documents uploaded yet. Add your hotel&apos;s FAQs, policies, and information.
          </p>
        )}
      </div>
    </div>
  )
}
