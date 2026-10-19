using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
namespace ArchiveReader;
public record WorkflowRisk(string Label);
public partial class RecognitionWorkflowWindow:Window
{
 readonly string page,engine;readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>> call;
 JsonObject? profile;bool busy;
 public string? Action{get;private set;}
 static string T(string value)=>Localizer.Text(value);
 public RecognitionWorkflowWindow(string page,string engine,Func<string,JsonObject?,CancellationToken,Task<JsonNode>> call)
 {this.page=page;this.engine=engine;this.call=call;InitializeComponent();Localizer.Apply(this,Localizer.Language);Loaded+=async(_,_)=>await Run(Refresh);}
 async Task Run(Func<Task> work){if(busy)return;busy=true;try{await work();}catch(Exception e){Status.Text=e.Message;}finally{busy=false;}}
 async Task Refresh()
 {
  var r=await call("workflow_status",new(){["id"]=page},default);profile=r["profile"]!.DeepClone().AsObject();Writer.Text=profile["values"]?["writer"]?.ToString()??"";
  Summary.Text=Localizer.Format("Зразків писаря: {0} · підтверджених прикладів: {1} · застарілих: {2} · роль книги: {3}",r["writer_exemplars"],r["examples"]?["confirmed"],r["examples"]?["stale"],r["split"]);
  Status.Text=T("Попередження не є виправленнями. Оригінальний текст зберігається.")+" "+T(engine=="kraken"?"Донавчання доступне лише в окрему копію моделі.":"Для цього рушія доступний експорт прикладів; донавчання в програмі не підключено.");
  Risks.ItemsSource=r["risks"]!.AsArray().Select(row=>new WorkflowRisk((row!["index"]!=null?"#"+(row["index"]!.GetValue<int>()+1):T("Ділянка"))+" · "+string.Join(", ",row["flags"]!.AsArray().Select(f=>T(f!.ToString() switch{"empty_output"=>"Порожній результат","untranscribed_annotation"=>"Ще немає транскрипції","repeated_text"=>"Повторюваний текст","short_fragment"=>"Короткий фрагмент","check_dates_numbers"=>"Перевірити дати й числа","check_person" or "check_related1" or "check_related2"=>"Перевірити ім’я","check_house"=>"Перевірити будинок",_=>"Перевірити дату"})))+" · "+row["text"])).ToList();
 }
 async void SaveWriter(object s,RoutedEventArgs e)=>await Run(async()=>{if(profile==null)return;var values=profile["values"]!.DeepClone().AsObject();values["writer"]=Writer.Text;await call("historical_profile",new(){["page"]=page,["expected"]=profile["signature"]!.DeepClone(),["values"]=values},default);await Refresh();});
 void Open(object s,RoutedEventArgs e){if(busy)return;Action=((Button)s).Tag.ToString();DialogResult=true;}
 async void Export(object s,RoutedEventArgs e)=>await Run(async()=>{var folder=new OpenFolderDialog();if(folder.ShowDialog()!=true)return;await call("dataset_explicit",new(){["path"]=folder.FolderName},default);Status.Text=T("Експортовано лише придатні підтверджені приклади з розділенням наборів.");});
}
