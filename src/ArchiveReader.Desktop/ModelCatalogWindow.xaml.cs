using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
namespace ArchiveReader;
public record CatalogModel(string Name,string Path,string[] Languages,string Scope,string Url,bool Selectable,string Engine){public bool Installed=>Selectable&&File.Exists(Path);public string Label=>Name+" · "+(Installed?"встановлена":"не підключена");}
public partial class ModelCatalogWindow:Window
{
 readonly List<CatalogModel> entries=[];
 readonly Func<string,JsonObject?,CancellationToken,Task<JsonNode>>? call;int selectionVersion;
 public string? SelectedModel{get;private set;}
 public string SelectedEngine{get;private set;}="kraken";
 public ModelCatalogWindow(string python,Func<string,JsonObject?,CancellationToken,Task<JsonNode>>? call=null)
 {
  this.call=call;
  InitializeComponent();
  Localizer.Apply(this,Localizer.Language);
  var starts=new[]{AppContext.BaseDirectory,System.IO.Path.GetDirectoryName(python)??AppContext.BaseDirectory};
  var modelRoots=new List<string>();
  foreach(var start in starts)for(var dir=new DirectoryInfo(start);dir!=null;dir=dir.Parent)modelRoots.Add(System.IO.Path.Combine(dir.FullName,"models"));
  var catalog=JsonNode.Parse(File.ReadAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"recognition_catalog.json")))!;
  foreach(var row in catalog["models"]!.AsArray())
  {
   var relative=row!["file"]!.ToString();var paths=modelRoots.Select(root=>System.IO.Path.Combine(root,relative)).ToList();var path=paths.FirstOrDefault(File.Exists)??paths[0];
   entries.Add(new(row["name"]!.ToString(),path,row["languages"]!.AsArray().Select(x=>x!.ToString()).ToArray(),row["scope"]!.ToString(),row["url"]!.ToString(),row["selectable"]?.GetValue<bool>()??true,row["engine"]?.ToString()??"kraken"));
  }
  DocumentLanguage.Items.Add("Усі мови");foreach(var lang in entries.SelectMany(x=>x.Languages).Distinct().Order())DocumentLanguage.Items.Add(lang);DocumentLanguage.SelectedIndex=0;Models.SelectedIndex=0;
 }
 void Filter(object sender,SelectionChangedEventArgs e){if(Models==null)return;Models.ItemsSource=entries.Where(x=>DocumentLanguage.SelectedIndex==0||x.Languages.Contains(DocumentLanguage.SelectedItem?.ToString()??"")).ToList();Details.Text="";ApplyButton.IsEnabled=false;}
 async void Select(object sender,SelectionChangedEventArgs e)
 {
  var version=++selectionVersion;var model=Models.SelectedItem as CatalogModel;ApplyButton.IsEnabled=model?.Installed==true;Details.Text=model==null?"":string.Join(", ",model.Languages)+"\n\n"+model.Scope+(model.Installed?"":"\n\nМодель відсутня на цьому комп’ютері.");
  if(model?.Installed!=true||call==null)return;
  try{var r=await call("workflow_model_status",new(){["model"]=model.Path,["engine"]=model.Engine},default);if(version!=selectionVersion)return;ApplyButton.IsEnabled=r["configured"]?.GetValue<bool>()==true;Details.Text+="\n\n"+Localizer.Format("Локальний розмір: {0} МБ · компоненти: {1}",(r["local_bytes"]!.GetValue<long>()/1048576d).ToString("F1"),string.Join(", ",r["components"]!.AsArray().Select(c=>c!["name"]+": "+(c["available"]!.GetValue<bool>()?"✓":"—"))))+"\n"+Localizer.Text("Перевірку точності на цій книзі відкрийте окремо. Наявність файлів не є перевіркою якості.");}catch(Exception ex){if(version==selectionVersion){ApplyButton.IsEnabled=false;Details.Text+="\n"+ex.Message;}}
 }
 void Apply(object sender,RoutedEventArgs e){if(Models.SelectedItem is CatalogModel model&&model.Installed){SelectedModel=model.Path;SelectedEngine=model.Engine;DialogResult=true;}}
 void Source(object sender,RoutedEventArgs e){if(Models.SelectedItem is CatalogModel model)Process.Start(new ProcessStartInfo(model.Url){UseShellExecute=true});}
}
