#property strict

#define EXPORT_VERSION "mt5-calendar-v1"
#define REQUIRED_TERMINAL_DIRECTORY "C:\\Program Files\\FBS MetaTrader 5"
#define REQUIRED_TERMINAL_EXE "C:\\Program Files\\FBS MetaTrader 5\\terminal64.exe"
#define REQUIRED_SERVER "FBS-Demo"
#define EVENTS_FILE "GSCALP\\mt5_calendar_events.csv"
#define METADATA_FILE "GSCALP\\mt5_calendar_metadata.csv"
#define EVENTS_PARTIAL_FILE "GSCALP\\mt5_calendar_events.csv.partial"
#define METADATA_PARTIAL_FILE "GSCALP\\mt5_calendar_metadata.csv.partial"

const datetime REQUESTED_FROM_SERVER = D'2020.01.01 00:00:00';
const datetime REQUESTED_TO_SERVER = D'2026.08.01 00:00:00';
const uint CONNECTION_TIMEOUT_MS = 60000;
const string EVENT_HEADER = "query_currency,query_start_server,query_end_server,query_count,query_error,value_id,event_id,event_time_server,event_time_mode_code,event_time_mode_name,event_importance_code,event_importance_name,country_id,event_code,event_name,source_url";


bool IsBlank(const string value)
  {
   string copy=value;
   StringTrimLeft(copy);
   StringTrimRight(copy);
   return StringLen(copy)==0;
  }


bool ContainsLineBreak(const string value)
  {
   return StringFind(value,"\r")>=0 || StringFind(value,"\n")>=0;
  }


bool IsKnownTimeMode(const ENUM_CALENDAR_EVENT_TIMEMODE value)
  {
   return value==CALENDAR_TIMEMODE_DATETIME ||
          value==CALENDAR_TIMEMODE_DATE ||
          value==CALENDAR_TIMEMODE_NOTIME ||
          value==CALENDAR_TIMEMODE_TENTATIVE;
  }


bool IsKnownImportance(const ENUM_CALENDAR_EVENT_IMPORTANCE value)
  {
   return value==CALENDAR_IMPORTANCE_NONE ||
          value==CALENDAR_IMPORTANCE_LOW ||
          value==CALENDAR_IMPORTANCE_MODERATE ||
          value==CALENDAR_IMPORTANCE_HIGH;
  }


string ServerTimeString(const datetime value)
  {
   return TimeToString(value,TIME_DATE|TIME_SECONDS);
  }


datetime NextMonth(const datetime value)
  {
   MqlDateTime parts={};
   if(!TimeToStruct(value,parts))
      return 0;
   parts.day=1;
   parts.hour=0;
   parts.min=0;
   parts.sec=0;
   if(parts.mon==12)
     {
      parts.year++;
      parts.mon=1;
     }
   else
      parts.mon++;
   return StructToTime(parts);
  }


bool DeleteIfPresent(const string filename,string &failure)
  {
   ResetLastError();
   if(!FileIsExist(filename))
     {
      ResetLastError();
      return true;
     }
   ResetLastError();
   if(!FileDelete(filename))
     {
      failure=StringFormat("cannot delete %s error=%d",filename,GetLastError());
      return false;
     }
   return true;
  }


void CleanupPartialFiles()
  {
   ResetLastError();
   if(FileIsExist(EVENTS_PARTIAL_FILE))
      FileDelete(EVENTS_PARTIAL_FILE);
   ResetLastError();
   if(FileIsExist(METADATA_PARTIAL_FILE))
      FileDelete(METADATA_PARTIAL_FILE);
   ResetLastError();
  }


bool WaitForConnectedTerminal(const uint timeout_ms,string &failure)
  {
   ulong started=GetTickCount64();
   while(!TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      if(IsStopped())
        {
         failure="script stopped while waiting for terminal connection";
         return false;
        }
      if(GetTickCount64()-started>=timeout_ms)
        {
         failure=StringFormat("terminal connection timeout after %u ms",timeout_ms);
         return false;
        }
      Sleep(250);
     }
   return true;
  }


bool ValidateEnvironment(string &failure)
  {
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      failure="terminal is not connected";
      return false;
     }

   string terminal_path=TerminalInfoString(TERMINAL_PATH);
   if(terminal_path!=REQUIRED_TERMINAL_DIRECTORY)
     {
      failure=StringFormat("terminal path mismatch expected=%s actual=%s",REQUIRED_TERMINAL_DIRECTORY,terminal_path);
      return false;
     }

   string server=AccountInfoString(ACCOUNT_SERVER);
   if(server!=REQUIRED_SERVER)
     {
      failure=StringFormat("account server mismatch expected=%s actual=%s",REQUIRED_SERVER,server);
      return false;
     }

   ENUM_ACCOUNT_TRADE_MODE trade_mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(trade_mode!=ACCOUNT_TRADE_MODE_DEMO)
     {
      failure=StringFormat("account trade mode is not demo actual=%d",(int)trade_mode);
      return false;
     }

   ENUM_ACCOUNT_MARGIN_MODE margin_mode=(ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      failure=StringFormat("account margin mode is not retail hedging actual=%d",(int)margin_mode);
      return false;
     }
   return true;
  }


void SortStrings(string &values[])
  {
   int size=ArraySize(values);
   for(int i=1;i<size;i++)
     {
      string current=values[i];
      int j=i-1;
      while(j>=0 && StringCompare(values[j],current,true)>0)
        {
         values[j+1]=values[j];
         j--;
        }
      values[j+1]=current;
     }
  }


bool ReadCalendarCurrencies(string &joined,string &failure)
  {
   MqlCalendarCountry countries[];
   ResetLastError();
   int count=CalendarCountries(countries);
   int error=GetLastError();
   if(count<=0 || error!=0 || ArraySize(countries)!=count)
     {
      failure=StringFormat("CalendarCountries failed count=%d size=%d error=%d",count,ArraySize(countries),error);
      return false;
     }

   string currencies[];
   for(int i=0;i<count;i++)
     {
      string currency=countries[i].currency;
      StringTrimLeft(currency);
      StringTrimRight(currency);
      if(StringLen(currency)==0)
         continue;
      bool exists=false;
      for(int j=0;j<ArraySize(currencies);j++)
        {
         if(currencies[j]==currency)
           {
            exists=true;
            break;
           }
        }
      if(exists)
         continue;
      int next_size=ArraySize(currencies)+1;
      if(ArrayResize(currencies,next_size)!=next_size)
        {
         failure="cannot allocate calendar currency list";
         return false;
        }
      currencies[next_size-1]=currency;
     }

   if(ArraySize(currencies)==0)
     {
      failure="CalendarCountries returned no nonblank currencies";
      return false;
     }
   SortStrings(currencies);
   joined=currencies[0];
   for(int i=1;i<ArraySize(currencies);i++)
      joined+=";"+currencies[i];
   return true;
  }


bool WriteMetadataRow(const int metadata,const string key,const string value)
  {
   ResetLastError();
   uint written=FileWrite(metadata,key,value);
   return written>0 && GetLastError()==0;
  }


bool WriteMetadataRows(const int metadata,
                       const datetime generated_server,
                       const datetime current_server,
                       const datetime current_gmt,
                       const string calendar_currencies,
                       const bool complete,
                       string &failure)
  {
   if(FileWrite(metadata,"key","value")==0)
     {
      failure="cannot write metadata header";
      return false;
     }
   if(!WriteMetadataRow(metadata,"script_version",EXPORT_VERSION) ||
      !WriteMetadataRow(metadata,"terminal_path",REQUIRED_TERMINAL_EXE) ||
      !WriteMetadataRow(metadata,"terminal_build",IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD))) ||
      !WriteMetadataRow(metadata,"terminal_company",TerminalInfoString(TERMINAL_COMPANY)) ||
      !WriteMetadataRow(metadata,"account_server",AccountInfoString(ACCOUNT_SERVER)) ||
      !WriteMetadataRow(metadata,"account_trade_mode",IntegerToString((int)AccountInfoInteger(ACCOUNT_TRADE_MODE))) ||
      !WriteMetadataRow(metadata,"account_margin_mode",IntegerToString((int)AccountInfoInteger(ACCOUNT_MARGIN_MODE))) ||
      !WriteMetadataRow(metadata,"requested_from_server",ServerTimeString(REQUESTED_FROM_SERVER)) ||
      !WriteMetadataRow(metadata,"requested_to_server",ServerTimeString(REQUESTED_TO_SERVER)) ||
      !WriteMetadataRow(metadata,"generated_at_server",ServerTimeString(generated_server)) ||
      !WriteMetadataRow(metadata,"current_server_time",ServerTimeString(current_server)) ||
      !WriteMetadataRow(metadata,"current_gmt_time",ServerTimeString(current_gmt)) ||
      !WriteMetadataRow(metadata,"calendar_currencies",calendar_currencies))
     {
      failure=StringFormat("cannot write metadata row error=%d",GetLastError());
      return false;
     }
   if(complete)
     {
      if(!WriteMetadataRow(metadata, "export_status", "complete"))
        {
         failure=StringFormat("cannot write complete metadata status error=%d",GetLastError());
         return false;
        }
     }
   else
     {
      if(!WriteMetadataRow(metadata, "export_status", "started"))
        {
         failure=StringFormat("cannot write started metadata status error=%d",GetLastError());
         return false;
        }
     }
   return true;
  }


bool FlushAndClose(const int handle,const string label,string &failure)
  {
   ResetLastError();
   FileFlush(handle);
   int flush_error=GetLastError();
   ResetLastError();
   FileClose(handle);
   int close_error=GetLastError();
   if(flush_error!=0 || close_error!=0)
     {
      failure=StringFormat("cannot finalize %s flush_error=%d close_error=%d",label,flush_error,close_error);
      return false;
     }
   return true;
  }


bool WriteMetadataFile(const datetime generated_server,
                       const datetime current_server,
                       const datetime current_gmt,
                       const string calendar_currencies,
                       const bool complete,
                       string &failure)
  {
   ResetLastError();
   int metadata=FileOpen(METADATA_PARTIAL_FILE,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(metadata==INVALID_HANDLE)
     {
      failure=StringFormat("cannot open metadata partial error=%d",GetLastError());
      return false;
     }
   if(!WriteMetadataRows(metadata,generated_server,current_server,current_gmt,calendar_currencies,complete,failure))
     {
      FileClose(metadata);
      return false;
     }
   return FlushAndClose(metadata,"metadata partial",failure);
  }


bool CalendarValueComesAfter(const MqlCalendarValue &left,const MqlCalendarValue &right)
  {
   if(left.time!=right.time)
      return left.time>right.time;
   if(left.event_id!=right.event_id)
      return left.event_id>right.event_id;
   return left.id>right.id;
  }


void SortCalendarValues(MqlCalendarValue &values[])
  {
   int size=ArraySize(values);
   for(int i=1;i<size;i++)
     {
      MqlCalendarValue current=values[i];
      int j=i-1;
      while(j>=0 && CalendarValueComesAfter(values[j],current))
        {
         values[j+1]=values[j];
         j--;
        }
      values[j+1]=current;
     }
  }


bool RecordValueId(const ulong value_id,ulong &seen_ids[],string &failure)
  {
   for(int i=0;i<ArraySize(seen_ids);i++)
     {
      if(seen_ids[i]==value_id)
        {
         failure=StringFormat("duplicate calendar value id=%I64u",value_id);
         return false;
        }
     }
   int next_size=ArraySize(seen_ids)+1;
   if(ArrayResize(seen_ids,next_size)!=next_size)
     {
      failure="cannot allocate calendar value ID audit list";
      return false;
     }
   seen_ids[next_size-1]=value_id;
   return true;
  }


bool WriteQueryStatus(const int events,
                      const string currency,
                      const datetime month_start,
                      const datetime month_end,
                      const int count,
                      const int error,
                      string &failure)
  {
   ResetLastError();
   uint written=FileWrite(events,
                          currency,
                          ServerTimeString(month_start),
                          ServerTimeString(month_end),
                          count,
                          error,
                          "","","","","","","","","","","");
   if(written==0 || GetLastError()!=0)
     {
      failure=StringFormat("cannot write query status currency=%s month=%s error=%d",currency,ServerTimeString(month_start),GetLastError());
      return false;
     }
   return true;
  }


bool WriteEvent(const int events,
                const string currency,
                const datetime month_start,
                const datetime month_end,
                const int count,
                const int query_error,
                const MqlCalendarValue &value,
                const MqlCalendarEvent &event,
                string &failure)
  {
   string time_mode_name=EnumToString(event.time_mode);
   string importance_name=EnumToString(event.importance);
   if(!IsKnownTimeMode(event.time_mode) || !IsKnownImportance(event.importance) ||
      IsBlank(time_mode_name) || IsBlank(importance_name) ||
      IsBlank(event.event_code) || IsBlank(event.name) || IsBlank(event.source_url) ||
      ContainsLineBreak(event.event_code) || ContainsLineBreak(event.name) || ContainsLineBreak(event.source_url))
     {
      failure=StringFormat("invalid event metadata event_id=%I64u",value.event_id);
      return false;
     }
   if(value.time<month_start || value.time>=month_end)
     {
      failure=StringFormat("event outside query interval value_id=%I64u",value.id);
      return false;
     }

   ResetLastError();
   uint written=FileWrite(events,
                          currency,
                          ServerTimeString(month_start),
                          ServerTimeString(month_end),
                          count,
                          query_error,
                          value.id,
                          value.event_id,
                          ServerTimeString(value.time),
                          (int)event.time_mode,
                          time_mode_name,
                          (int)event.importance,
                          importance_name,
                          event.country_id,
                          event.event_code,
                          event.name,
                          event.source_url);
   if(written==0 || GetLastError()!=0)
     {
      failure=StringFormat("cannot write event value_id=%I64u error=%d",value.id,GetLastError());
      return false;
     }
   return true;
  }


bool ExportQuery(const int events,
                 const string currency,
                 const datetime month_start,
                 const datetime month_end,
                 ulong &seen_ids[],
                 string &failure)
  {
   MqlCalendarValue values[];
   ResetLastError();
   int count=CalendarValueHistory(values,month_start,month_end-1,NULL,currency);
   int error=GetLastError();
   if(count<0 || error!=0 || ArraySize(values)!=count)
     {
      failure=StringFormat("CalendarValueHistory failed currency=%s month=%s count=%d size=%d error=%d",currency,ServerTimeString(month_start),count,ArraySize(values),error);
      return false;
     }
   SortCalendarValues(values);
   if(!WriteQueryStatus(events,currency,month_start,month_end,count,error,failure))
      return false;

   for(int i=0;i<count;i++)
     {
      if(!RecordValueId(values[i].id,seen_ids,failure))
         return false;
      MqlCalendarEvent event={};
      ResetLastError();
      bool resolved=CalendarEventById(values[i].event_id,event);
      int event_error=GetLastError();
      if(!resolved || event_error!=0 || event.id!=values[i].event_id)
        {
         failure=StringFormat("CalendarEventById failed event_id=%I64u error=%d",values[i].event_id,event_error);
         return false;
        }
      if(!WriteEvent(events,currency,month_start,month_end,count,error,values[i],event,failure))
         return false;
     }
   return true;
  }


bool WriteEventsFile(string &failure)
  {
   ResetLastError();
   int events=FileOpen(EVENTS_PARTIAL_FILE,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(events==INVALID_HANDLE)
     {
      failure=StringFormat("cannot open events partial error=%d",GetLastError());
      return false;
     }
   ResetLastError();
   if(FileWrite(events,
                "query_currency","query_start_server","query_end_server","query_count","query_error",
                "value_id","event_id","event_time_server","event_time_mode_code","event_time_mode_name",
                "event_importance_code","event_importance_name","country_id","event_code","event_name","source_url")==0 ||
      GetLastError()!=0)
     {
      failure=StringFormat("cannot write event header error=%d",GetLastError());
      FileClose(events);
      return false;
     }

   ulong seen_ids[];
   datetime month_start=REQUESTED_FROM_SERVER;
   while(month_start<REQUESTED_TO_SERVER)
     {
      datetime month_end=NextMonth(month_start);
      if(month_end<=month_start || month_end>REQUESTED_TO_SERVER)
        {
         failure=StringFormat("invalid month boundary at %s",ServerTimeString(month_start));
         FileClose(events);
         return false;
        }
      if(!ExportQuery(events,"USD",month_start,month_end,seen_ids,failure) ||
         !ExportQuery(events,"XAU",month_start,month_end,seen_ids,failure))
        {
         FileClose(events);
         return false;
        }
      month_start=month_end;
     }
   return FlushAndClose(events,"events partial",failure);
  }


bool PublishCompletedExport(string &failure)
  {
   ResetLastError();
   if(!FileMove(EVENTS_PARTIAL_FILE,0,EVENTS_FILE,FILE_REWRITE))
     {
      failure=StringFormat("cannot publish events file error=%d",GetLastError());
      return false;
     }
   ResetLastError();
   if(!FileMove(METADATA_PARTIAL_FILE,0,METADATA_FILE,FILE_REWRITE))
     {
      int publish_error=GetLastError();
      ResetLastError();
      FileDelete(EVENTS_FILE);
      failure=StringFormat("cannot publish metadata file error=%d",publish_error);
      return false;
     }
   return true;
  }


void OnStart()
  {
   string failure="";
   CleanupPartialFiles();
   if(!DeleteIfPresent(EVENTS_FILE,failure) || !DeleteIfPresent(METADATA_FILE,failure))
     {
      PrintFormat("GSCALP_NEWS_EXPORT_FAILED reason=%s",failure);
      CleanupPartialFiles();
      return;
     }
   if(!WaitForConnectedTerminal(CONNECTION_TIMEOUT_MS,failure))
     {
      PrintFormat("GSCALP_NEWS_EXPORT_FAILED reason=%s",failure);
      CleanupPartialFiles();
      return;
     }
   if(!ValidateEnvironment(failure))
     {
      PrintFormat("GSCALP_NEWS_EXPORT_FAILED reason=%s",failure);
      CleanupPartialFiles();
      return;
     }

   string terminal_company=TerminalInfoString(TERMINAL_COMPANY);
   datetime generated_server=TimeTradeServer();
   datetime current_server=TimeTradeServer();
   datetime current_gmt=TimeGMT();
   string calendar_currencies="";
   if(IsBlank(terminal_company) || generated_server==0 || current_server==0 || current_gmt==0)
     {
      Print("GSCALP_NEWS_EXPORT_FAILED reason=invalid approved runtime metadata");
      CleanupPartialFiles();
      return;
     }
   if(!ReadCalendarCurrencies(calendar_currencies,failure))
     {
      PrintFormat("GSCALP_NEWS_EXPORT_FAILED reason=%s",failure);
      CleanupPartialFiles();
      return;
     }

   if(!WriteMetadataFile(generated_server,current_server,current_gmt,calendar_currencies,false,failure) ||
      !WriteEventsFile(failure) ||
      !WriteMetadataFile(generated_server,current_server,current_gmt,calendar_currencies,true,failure) ||
      !PublishCompletedExport(failure))
     {
      PrintFormat("GSCALP_NEWS_EXPORT_FAILED reason=%s",failure);
      CleanupPartialFiles();
      DeleteIfPresent(EVENTS_FILE,failure);
      DeleteIfPresent(METADATA_FILE,failure);
      return;
     }

   PrintFormat("GSCALP_NEWS_EXPORT_COMPLETE from=%s to=%s currencies=USD;XAU",ServerTimeString(REQUESTED_FROM_SERVER),ServerTimeString(REQUESTED_TO_SERVER));
  }
