"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';


function WebsiteForm() {
  const [url, setUrl] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [competitors, setCompetitors] = useState(['', '', '']);
  const router = useRouter();

  const setCompetitor = (index: number, value: string) => {
    setCompetitors(prev => prev.map((c, i) => i === index ? value : c));
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    try {
      const formData = new FormData();
      formData.append('url', url);
      formData.append('company_name', companyName);
      formData.append('competitor_1', competitors[0]);
      formData.append('competitor_2', competitors[1]);
      formData.append('competitor_3', competitors[2]);

      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits`, {
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
        <div className="flex flex-col gap-1.5">
          <label htmlFor="company_name" className="text-sm font-medium text-gray-600">Company Name</label>
          <input
            type="text"
            id="company_name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Acme Corp"
            required
            className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="url" className="text-sm font-medium text-gray-600">Website URL</label>
          <input
            type="url"
            id="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            required
            className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
          />
        </div>
      </div>

      {/* Competitors */}
      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium text-gray-600">Competitors</p>
        <div className="flex flex-col gap-3">
          {competitors.map((val, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <label htmlFor={`competitor_${i + 1}`} className="text-xs text-gray-400">
                Competitor {i + 1}
              </label>
              <input
                type="url"
                id={`competitor_${i + 1}`}
                value={val}
                onChange={(e) => setCompetitor(i, e.target.value)}
                placeholder={`https://competitor${i + 1}.com`}
                required
                className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
              />
            </div>
          ))}
        </div>
      </div>

      <button
        type="submit"
        className="bg-green-700 text-white rounded-xl px-6 py-3 font-semibold text-base hover:bg-green-800 active:scale-[0.98] transition-all mt-1"
      >
        Start Audit
      </button>
    </form>
  );
}


export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-6 py-12">
      <div className="flex flex-col items-center gap-8 w-full max-w-lg">

        {/* Header */}
        <div className="flex flex-col items-center gap-2 text-center">
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Powerling</h1>
          <p className="text-base font-semibold text-green-700">Pre-Audit</p>
          <p className="text-sm text-gray-400 mt-1">Automated website audit reports</p>
        </div>

        {/* Form card */}
        <div className="bg-white rounded-2xl shadow-md border border-gray-100 border-t-4 border-t-green-700 px-8 py-8 w-full">
          <WebsiteForm />
        </div>

      </div>
    </div>
  );
}
