"use client";

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';


function WebsiteForm() {
  const [url, setUrl] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [competitors, setCompetitors] = useState(['', '', '']);
  const [semrushFile, setSemrushFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const setCompetitor = (index: number, value: string) => {
    setCompetitors(prev => prev.map((c, i) => i === index ? value : c));
  };

  const handleFile = (file: File) => {
    if (file.type !== 'application/pdf') {
      toast.error('Please upload a PDF file.');
      return;
    }
    setSemrushFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!semrushFile) {
      toast.error('Please upload a SEMrush Site Audit PDF before submitting.');
      return;
    }
    try {
      const formData = new FormData();
      formData.append('url', url);
      formData.append('company_name', companyName);
      formData.append('competitor_1', competitors[0]);
      formData.append('competitor_2', competitors[1]);
      formData.append('competitor_3', competitors[2]);
      if (semrushFile) {
        formData.append('semrush_pdf', semrushFile);
      }

      const response = await fetch('http://localhost:8000/audits', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (response.ok) {
        toast.success("Job submitted with ID " + data.job_id, { duration: 3000 });
        router.push(`/audits/${data.job_id}`);
      } else {
        toast.error(data.detail || "Failed to create audit job.");
      }
    } catch (error) {
      console.error("Error:", error);
      toast.error("Error submitting job");
    }
  };

  return (
    <form className="flex flex-col gap-6 w-full" onSubmit={handleSubmit}>

      {/* Client info */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="company_name" className="font-semibold text-gray-700">Company Name</label>
          <input
            type="text"
            id="company_name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Acme Corp"
            required
            className="border border-gray-300 rounded-lg px-4 py-3 text-gray-800 focus:outline-none focus:ring-2 focus:ring-orange-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="url" className="font-semibold text-gray-700">Website URL</label>
          <input
            type="url"
            id="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            required
            className="border border-gray-300 rounded-lg px-4 py-3 text-gray-800 focus:outline-none focus:ring-2 focus:ring-orange-500"
          />
        </div>
      </div>

      {/* Competitors */}
      <div className="flex flex-col gap-3">
        <p className="font-semibold text-gray-700">Competitors</p>
        <div className="flex flex-col gap-3">
          {competitors.map((val, i) => (
            <div key={i} className="flex flex-col gap-1">
              <label htmlFor={`competitor_${i + 1}`} className="text-sm text-gray-500">
                Competitor {i + 1} URL
              </label>
              <input
                type="url"
                id={`competitor_${i + 1}`}
                value={val}
                onChange={(e) => setCompetitor(i, e.target.value)}
                placeholder={`https://competitor${i + 1}.com`}
                required
                className="border border-gray-300 rounded-lg px-4 py-3 text-gray-800 focus:outline-none focus:ring-2 focus:ring-orange-500"
              />
            </div>
          ))}
        </div>
      </div>

      {/* SEMrush PDF upload */}
      <div className="flex flex-col gap-2">
        <p className="font-semibold text-gray-700">SEMrush Site Audit PDF</p>
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-lg px-4 py-6 cursor-pointer transition
            ${isDragging ? 'border-orange-400 bg-orange-50' : 'border-gray-300 hover:border-orange-400 hover:bg-orange-50'}`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
          />
          {semrushFile ? (
            <div className="flex items-center gap-3 w-full">
              <span className="text-orange-500 text-xl">📄</span>
              <span className="text-gray-700 text-sm font-medium truncate flex-1">{semrushFile.name}</span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setSemrushFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
                className="text-gray-400 hover:text-red-500 text-sm transition"
              >
                Remove
              </button>
            </div>
          ) : (
            <>
              <span className="text-3xl text-gray-300">⬆</span>
              <p className="text-sm text-gray-500 text-center">
                Drag and drop your SEMrush PDF here, or <span className="text-orange-500 font-medium">click to browse</span>
              </p>
            </>
          )}
        </div>
      </div>

      <button
        type="submit"
        className="bg-orange-500 text-white rounded-lg px-6 py-3 font-semibold text-lg hover:bg-orange-600 transition"
      >
        Start Audit
      </button>
    </form>
  );
}


export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-orange-200 flex flex-col items-center justify-center px-6 py-12">
      <div className="flex flex-col items-center gap-10 w-full max-w-lg">
        <div className="flex flex-col items-center gap-3 text-center">
          <h1 className="text-5xl font-bold text-gray-900">Powerling</h1>
          <h2 className="text-3xl font-semibold text-orange-600">Pre-Audit</h2>
          <p className="text-gray-600 text-lg mt-2">Get a comprehensive audit of your website</p>
        </div>
        <WebsiteForm />
      </div>
    </div>
  );
}
